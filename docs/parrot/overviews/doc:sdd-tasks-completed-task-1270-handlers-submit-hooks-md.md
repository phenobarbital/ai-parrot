---
type: Wiki Overview
title: 'TASK-1270: Wire onBeforeSubmit, onAfterSubmit and onError into submit_data'
id: doc:sdd-tasks-completed-task-1270-handlers-submit-hooks-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 5 — the submit-path portion. This is the most intricate
  hook integration because three dispatches share a single try/except envelope and
  `onBeforeSubmit` may replace the payload before validation.
---

# TASK-1270: Wire onBeforeSubmit, onAfterSubmit and onError into submit_data

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1267, TASK-1268, TASK-1269
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 5 — the submit-path portion. This is the most intricate hook integration because three dispatches share a single try/except envelope and `onBeforeSubmit` may replace the payload before validation.

---

## Scope

- In `submit_data` (api/handlers.py:840):
  1. After loading the form and parsing JSON body (and after the partial-merge block, before validation):
     `await dispatch("onBeforeSubmit", form=form, payload=data, ...)`.
     If the resolution has `payload`, replace `data` with it.
  2. After successful store + forward, before returning:
     `await dispatch("onAfterSubmit", form=form, payload=submission.data, ...)`.
  3. Wrap the entire flow in a try/except envelope. Excluded from the envelope:
     - The initial 404 check (no events configured yet).
     - The JSON parse 400 check (no form loaded yet — no events available).
     - `FormEventAbort` from `onBeforeSubmit`: convert to typed JSON response with `status_code` and `user_message`. Do NOT route through `onError`.
  4. On ANY other exception (`ValidationError`, `MetadataResolutionError`, generic `Exception`):
     - Dispatch `onError` with `error=exc`. If the resolution has `user_message`, use it.
     - Re-raise the original exception so the framework / outer error handlers still produce a 500 / 422 (DO NOT suppress).
     - `onError` itself may raise — that secondary exception is logged as `meta_error` and the original exception still propagates.
- Add integration tests in `tests/integration/test_lifecycle_events_submit.py`.

**NOT in scope**: remote endpoint (TASK-1271), HTML5 renderer (TASK-1272), e2e docs (TASK-1273).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Insert 3 dispatches + try/except envelope around l.840 `submit_data` |
| `packages/parrot-formdesigner/tests/integration/test_lifecycle_events_submit.py` | CREATE | Integration tests for the submit flow |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already added by TASK-1269 — confirm they're present:
from parrot_formdesigner.services.event_dispatcher import dispatch, apply_schema_overrides
from parrot_formdesigner.core.events import FormEventAbort
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:840
async def submit_data(self, request: web.Request) -> web.Response:
    """POST /api/v1/forms/{form_id}/data — Receive and process a form submission."""
    # Key existing checkpoints:
    # l.856-871 — load form (404 if missing)
    # l.873-876 — parse JSON (400 if invalid)
    # l.878-902 — optional partial merge
    # l.904-910 — validate (422 on failure)
    # l.912-920 — build FormSubmission
    # l.922-941 — metadata enrichment (MetadataResolutionError → 422)
    # l.943-950 — submission storage
    # l.952-970 — forwarder
    # l.972-987 — partial cleanup
    # l.989-995 — return composite response
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/metadata_enricher.py:39
class MetadataResolutionError(Exception): ...  # already caught at handlers.py l.933
```

### Does NOT Exist

- ~~`self.event_bus` / `self.dispatcher`~~ — `dispatch` is a free function.
- ~~Any framework middleware that auto-dispatches lifecycle events~~ — no such mechanism; do it explicitly in this handler.

---

## Implementation Notes

### Insertion topology

```python
async def submit_data(self, request: web.Request) -> web.Response:
    # ... unchanged: form_id, tenant, form load, 404, JSON parse ...

    # NEW: lifecycle envelope begins HERE (after JSON parse so we have `data`)
    try:
        # ... unchanged: partial merge block ...

        # NEW: onBeforeSubmit (may mutate `data` or abort)
        try:
            resolution = await dispatch(
                "onBeforeSubmit",
                form=form, request=request,
                tenant=tenant,
                auth_context=self._build_auth_context(request),
                payload=data,
            )
            if resolution.payload is not None:
                data = dict(resolution.payload)
        except FormEventAbort as exc:
            return web.json_response(
                {"error": exc.user_message, "reason": exc.reason},
                status=exc.status_code,
            )

        # ... unchanged: validate, build submission, enrich, store, forward, partial cleanup ...

        # NEW: onAfterSubmit (best-effort; failures route via onError below)
        await dispatch(
            "onAfterSubmit",
            form=form, request=request,
            tenant=tenant,
            auth_context=self._build_auth_context(request),
            payload=submission.data,
        )

        return web.json_response({...unchanged...})

    except FormEventAbort:
        raise  # already handled above; this catch is here for clarity
    except Exception as exc:
        # NEW: onError envelope
        user_message: str | None = None
        try:
            err_resolution = await dispatch(
                "onError",
                form=form, request=request,
                tenant=tenant,
                auth_context=self._build_auth_context(request),
                error=exc,
            )
            user_message = err_resolution.user_message
        except Exception as meta_exc:
            self.logger.exception("onError handler itself raised: %s", meta_exc)
        # IMPORTANT: do NOT suppress — re-raise the original exception so
        # existing error pathways (ValidationError → 422, MetadataResolutionError → 422,
        # generic → 500) still produce the original status code.
        # The user_message, if any, is attached to the request state for the outer
        # error handler to pick up. If no outer handler exists, log and re-raise.
        if user_message:
            request["_lifecycle_user_message"] = user_message  # optional surfacing
        raise
```

### Key Constraints

- **Catch order matters**: `FormEventAbort` must be caught INSIDE the `try` that calls dispatch, not in the outer `except Exception`. Otherwise the outer envelope would route abort through `onError`, which is explicitly forbidden by spec §7.
- **Existing 422 paths**: `ValidationError` and `MetadataResolutionError` currently return 422 directly (l.906-910 and l.933-937). After the envelope is added, these must STILL produce 422 — the easiest way is to keep their explicit `return web.json_response(..., status=422)` lines unchanged and have the outer `except Exception` only catch what falls through. If implementing this way, `onError` must be invoked from the existing 422-branches as well (call `dispatch("onError", ...)` immediately before each early return). Pick this approach for minimal disruption.
- The `submission.data` passed to `onAfterSubmit` is the post-enrichment value (after `metadata_enricher.enrich_submission` and any `extra_flat` merge).
- Backward compat: forms without `events` produce byte-identical responses.

### References in Codebase

- `api/handlers.py:933-937` — pattern for `MetadataResolutionError` early return.
- `services/metadata_enricher.py:39` — `MetadataResolutionError`.

---

## Acceptance Criteria

- [ ] `submit_data` for a form WITHOUT `events` returns byte-identical responses to pre-change (regression-free).
- [ ] `onBeforeSubmit` handler that returns `EventResolution(payload={...normalized...})` → validator sees the normalized payload.
- [ ] `onBeforeSubmit` handler raising `FormEventAbort` → HTTP `status_code` + `user_message`; validator NOT called.
- [ ] `onAfterSubmit` handler called after store + forward (mock side-effect verified).
- [ ] `onError` handler called when validator returns `is_valid=False`; the 422 response is still produced.
- [ ] `onError` handler called when `MetadataResolutionError` is raised; the 422 is still produced.
- [ ] `onError` handler raising itself does NOT mask the original error; original status code preserved.
- [ ] `FormEventAbort` is NEVER routed to `onError` (spec §7).
- [ ] All new integration tests pass.
- [ ] All existing `submit_data` tests still pass.
- [ ] `ruff` clean.

---

## Test Specification

```python
# tests/integration/test_lifecycle_events_submit.py
import pytest
from parrot_formdesigner.core.events import (
    EventResolution, FormEventAbort, FormEventBinding, FormEventsConfig,
)
from parrot_formdesigner.services.event_registry import (
    register_form_event, _clear_event_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _clear():
    yield
    _clear_event_registry_for_tests()


async def test_submit_without_events_unchanged(api_client, form_no_events):
    resp = await api_client.post(
        f"/api/v1/forms/{form_no_events.form_id}/data",
        json={"name": "x"},
    )
    assert resp.status == 200

async def test_onbeforesubmit_normalizes_payload(api_client, form_email):
    @register_form_event("f_email.onBeforeSubmit")
    async def normalize(ctx):
        p = dict(ctx.payload)
        p["email"] = p["email"].strip().lower()
        return EventResolution(payload=p)

    resp = await api_client.post(
        f"/api/v1/forms/{form_email.form_id}/data",
        json={"email": "  USER@Example.com  "},
    )
    assert resp.status == 200
    # then assert the persisted value is "user@example.com"

async def test_onbeforesubmit_abort_returns_status(api_client, form_with_submit_hook):
    @register_form_event("f1.onBeforeSubmit")
    async def block(ctx):
        raise FormEventAbort("nope", user_message="Blocked", status_code=409)

    resp = await api_client.post(
        f"/api/v1/forms/{form_with_submit_hook.form_id}/data",
        json={},
    )
    assert resp.status == 409
    body = await resp.json()
    assert body["error"] == "Blocked"

async def test_onerror_does_not_suppress(api_client, form_with_validation):
    called = []

    @register_form_event("fv.onError")
    async def collect(ctx):
        called.append(type(ctx.error).__name__)
        return EventResolution(user_message="Friendly")

    resp = await api_client.post(
        f"/api/v1/forms/{form_with_validation.form_id}/data",
        json={"required_field": None},
    )
    assert resp.status == 422
    assert called  # onError was invoked
```

---

## Agent Instructions

1. **Read the spec** §3 Module 5 (submit portion) and §7 Patterns (`onError` does NOT fire for `FormEventAbort`).
2. **Check dependencies** — TASK-1267, TASK-1268, TASK-1269.
3. **Verify the Codebase Contract** — re-read `api/handlers.py:840-995` before editing.
4. **Implement** — be very careful about where the try/except envelope starts and ends; the 422 early returns must STILL fire `onError` per the implementation note.
5. **Verify** acceptance criteria.
6. **Move** this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
