# TASK-2428: Branch the submit path - exclusive sink write and status mapping

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2426, TASK-2420, TASK-2421
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 12

---

## Context

Where the feature becomes real. Today `submit_data` calls the generic submission
storage unconditionally. After this task, a form with a `persistence:` block writes ONLY to
its own sink, and the generic storage is skipped entirely - the **exclusivity** guarantee that
is the central acceptance criterion of FEAT-457.

Also maps the sink error taxonomy onto HTTP and gates the read endpoints on capabilities.

Implements spec section 3 Module 12.

---

## Scope

- Modify `FormAPIHandler.__init__` (`api/handlers.py:138`) to accept an optional `sink_factory`, stored alongside `self._submission_storage` (`:154`).
- Replace the block at `api/handlers.py:1615-1622` with a branch: when `form.persistence` is set -> resolve the sink via the factory, `ensure_target(form)`, map the submission (`flatten_submission` or `nest_submission` per the sink's family), `write()`, and SKIP the generic storage. Otherwise -> today's code, verbatim.
- Map `SinkUnavailableError` -> `503` with a `Retry-After` header; `SinkNotCapableError` -> `501`; `SinkTargetMismatchError` -> `422`.
- Dispatch `onError` best-effort before each early error return, consistent with the existing validation (`:1552`) and metadata (`:1596`) error paths.
- Gate `get_submission` and `list_revisions` on the sink's capabilities, returning `501` with the sink type and its declared capabilities in the body.
- Update the `submit_data` docstring flow list (`api/handlers.py:1443-1454`) to describe the branch.
- Leave the forwarder block (`api/handlers.py:1624-1631`) untouched.
- Write unit tests in `tests/unit/test_submit_path_branch.py`.

**NOT in scope**: App wiring / constructing the factory (TASK-2429). The end-to-end integration suite (TASK-2430). Any change to `FormSubmissionStorage`. Any change to the forwarder or to `SubmitAction`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Constructor arg + submit branch + capability gating + docstring |
| `packages/parrot-formdesigner/tests/unit/test_submit_path_branch.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Added to api/handlers.py (follow the file's existing TYPE_CHECKING + local-import style -
# see the local imports inside submit_data at lines 1456-1462):
from ..services.sinks.base import (                       # TASK-2419
    SinkUnavailableError, SinkNotCapableError, SinkTargetMismatchError,
)
from ..services.sinks.factory import SinkFactory          # TASK-2426
from ..services.sinks.mapper import flatten_submission, nest_submission  # TASK-2420
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:108 - the class to modify
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client=None,
                 submission_storage: "FormSubmissionStorage | None" = None,
                 forwarder=None, partial_store=None, org_graph_service=None,
                 project_service=None, rbac_service=None, workday_adapter=None,
                 venue_service=None, rbac_enforcing: bool = False) -> None: ...   # line 138
    #   line 154: self._submission_storage = submission_storage

    async def submit_data(self, request: web.Request) -> web.Response: ...        # line 1440
    #   lines 1443-1454: the documented 8-step flow - UPDATE THIS DOCSTRING
    #   line 1568: submission = FormSubmission(...)
    #   line 1582: metadata enrichment via enrich_submission
    #   line 1615: "# Store locally (if storage configured)"       <- START of block to replace
    #   line 1616:     if self._submission_storage is not None:
    #   line 1617:         await self._submission_storage.store(submission)   <- THE call
    #   lines 1618-1622: else + self.logger.debug(...)             <- END of block to replace
    #   line 1624: "# Forward to endpoint ..."                     <- LEAVE UNTOUCHED
    #   line 1628: if form.submit is not None and form.submit.action_type == "endpoint" ...
    #   line 1629:     await self._forwarder.forward(result.sanitized_data, form.submit)
```

> WARNING: The brainstorm cited the call site as `:1616`. That line is the `if` guard. The
> actual `store(submission)` call is at **`:1617`** and the block to replace is
> **`:1615-1622`**. Re-`grep` before editing - the line numbers shift as soon as anything
> above them changes.

```python
# Existing best-effort onError dispatch idiom to copy (validation path, ~line 1552):
try:
    _err_res = await dispatch("onError", form=form, request=request, tenant=tenant,
                              auth_context=_auth_ctx, error=_validation_exc)
except Exception as _meta_exc:
    self.logger.exception("onError handler raised during validation: %s", _meta_exc)
```

### Does NOT Exist

- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.
- ~~a `persistence` branch already present in `submit_data`~~ - the store call is unconditional on `dev`. Verify with `sed -n 1615,1622p packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`.
- ~~`self._sink_factory` existing~~ - this task introduces it.
- ~~modifying `FormSubmissionStorage`~~ - out of scope and forbidden. The generic storage is simply not called for autonomous forms.
- ~~a `Retry-After` helper in this package~~ - none exists; set the header directly on the `web.Response`.

---

## Implementation Notes

### Pattern to Follow

Branch, do not extend. Exclusivity means the generic call is *skipped*, not made and undone:

```python
# Replaces api/handlers.py:1615-1622
if form.persistence is not None:
    try:
        sink = await self._sink_factory.get(form, tenant=tenant)
        await sink.ensure_target(form)
        payload = (nest_submission if sink.is_document else flatten_submission)(form, submission)
        await sink.write(submission, payload)
    except SinkUnavailableError as exc:
        await _dispatch_on_error_best_effort(exc)
        return JSONResponse({"error": str(exc)}, status=503,
                            headers={"Retry-After": "30"})
    except SinkTargetMismatchError as exc:
        await _dispatch_on_error_best_effort(exc)
        return JSONResponse({"error": str(exc)}, status=422)
elif self._submission_storage is not None:
    await self._submission_storage.store(submission)      # unchanged path
else:
    self.logger.debug(...)                                 # unchanged path
```

### Key Constraints

- EXCLUSIVITY IS THE CENTRAL CRITERION: when `form.persistence` is set, `self._submission_storage.store` must NEVER be called. Assert it with a mock, do not merely observe an empty table.
- `persistence is None` must take today's code path with zero behavioural change.
- Never fall back to the generic table on sink failure - that would break exclusivity.
- `onError` dispatch is best-effort and must not mask the original error.
- Do NOT touch lines 1624-1631 (the forwarder).
- Re-`grep` the line numbers before editing; they shift with any edit above them.
- Update the docstring flow list - a stale 8-step docstring is a documentation bug.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1615-1622` - the block to replace
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1552` - the best-effort `onError` idiom to copy
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1628` - the forwarder block to leave alone
- `packages/parrot-formdesigner/tests/test_submit_merge.py` - existing submit-path test conventions

---

## Acceptance Criteria

- [ ] With `persistence` set, `FormSubmissionStorage.store` is NOT called (asserted with a mock)
- [ ] With `persistence` set, the sink's `ensure_target` and `write` ARE called, in that order
- [ ] With `persistence is None`, the generic storage IS called exactly as before
- [ ] `SinkUnavailableError` -> `503` with a `Retry-After` header and nothing persisted
- [ ] `SinkTargetMismatchError` -> `422`
- [ ] `SinkNotCapableError` on a read endpoint -> `501` naming the sink type and capabilities
- [ ] `onError` is dispatched on each sink failure path and a raising handler does not mask the error
- [ ] Document-family sinks receive a nested payload; tabular ones receive a flat row
- [ ] `git diff` on `services/forwarder.py` is empty and lines 1624-1631 are unchanged
- [ ] The `submit_data` docstring flow list mentions the persistence branch
- [ ] `pytest packages/parrot-formdesigner/tests/ -k submit -v` passes (including pre-existing tests)
- [ ] `ruff` and `mypy` clean on `api/handlers.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_submit_path_branch.py
from unittest.mock import AsyncMock

import pytest


class TestExclusivity:
    async def test_generic_storage_not_called(self, handler, autonomous_form, post_data):
        handler._submission_storage.store = AsyncMock()
        await handler.submit_data(post_data(autonomous_form))
        handler._submission_storage.store.assert_not_called()

    async def test_sink_called_in_order(self, handler, autonomous_form, post_data, fake_sink):
        await handler.submit_data(post_data(autonomous_form))
        assert fake_sink.calls == ["ensure_target", "write"]

    async def test_plain_form_uses_generic_storage(self, handler, plain_form, post_data):
        handler._submission_storage.store = AsyncMock()
        await handler.submit_data(post_data(plain_form))
        handler._submission_storage.store.assert_awaited_once()


class TestStatusMapping:
    async def test_unavailable_is_503_with_retry_after(self, handler, autonomous_form, post_data, sink_down):
        resp = await handler.submit_data(post_data(autonomous_form))
        assert resp.status == 503
        assert "Retry-After" in resp.headers

    async def test_nothing_persisted_on_503(self, handler, autonomous_form, post_data, sink_down):
        handler._submission_storage.store = AsyncMock()
        await handler.submit_data(post_data(autonomous_form))
        handler._submission_storage.store.assert_not_called()

    async def test_mismatch_is_422(self, handler, autonomous_form, post_data, sink_mismatch):
        assert (await handler.submit_data(post_data(autonomous_form))).status == 422

    async def test_read_on_write_only_sink_is_501(self, handler, csv_form, get_submission_request):
        resp = await handler.get_submission(get_submission_request(csv_form))
        assert resp.status == 501


class TestPayloadFamily:
    async def test_document_sink_gets_nested(self, handler, mongo_form, post_data, fake_doc_sink):
        await handler.submit_data(post_data(mongo_form))
        assert "data" in fake_doc_sink.written[-1]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
