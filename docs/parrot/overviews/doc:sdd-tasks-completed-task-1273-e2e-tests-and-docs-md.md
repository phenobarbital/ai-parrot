---
type: Wiki Overview
title: 'TASK-1273: End-to-end tests, documentation and CHANGELOG'
id: doc:sdd-tasks-completed-task-1273-e2e-tests-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Final task. Ties everything together with:'
---

# TASK-1273: End-to-end tests, documentation and CHANGELOG

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1265, TASK-1266, TASK-1267, TASK-1268, TASK-1269, TASK-1270, TASK-1271, TASK-1272
**Assigned-to**: unassigned

---

## Context

Final task. Ties everything together with:
- Broad end-to-end integration tests that exercise the full lifecycle (HTTP layer → dispatcher → handler → response).
- Backward-compatibility regression test (forms without `events` must be byte-identical).
- User-facing documentation with worked examples.
- CHANGELOG entry.

---

## Scope

- Create `tests/integration/test_lifecycle_events_e2e.py` covering:
  - All 5 events on a single form, registered, fired, and observed via the HTTP API.
  - The backward-compatibility acid test (no `events` → identical responses).
  - The interaction between `onBeforeSubmit.payload` and downstream metadata enrichment.
- Add documentation in `packages/parrot-formdesigner/docs/lifecycle-events.md` (or extend existing docs index) with:
  - Quick-start example (register handler + declare in schema).
  - Reference of the 5 events: when they fire, what `ctx` carries, what can be returned/raised.
  - Server-side vs client-side guidance (`remote: true`).
  - CSRF behavior on the remote endpoint.
  - Known limitations (single handler per event, in-process CSRF, shallow merge).
- Update `packages/parrot-formdesigner/CHANGELOG.md` with an entry under the next release.

**NOT in scope**: Telegram parity, deep-merge `schema_overrides`, multi-handler chains — all explicitly post-MVP per spec.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/test_lifecycle_events_e2e.py` | CREATE | Full-stack tests |
| `packages/parrot-formdesigner/docs/lifecycle-events.md` | CREATE | User-facing docs |
| `packages/parrot-formdesigner/docs/index.md` | MODIFY (if exists) | Link to new doc |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | Add release entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test file imports the public surface only:
from parrot_formdesigner.core.events import (
    FormEventBinding, FormEventsConfig, FormEventAbort, EventResolution,
)
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services import register_form_event, dispatch  # re-exports
from parrot_formdesigner.services.event_registry import _clear_event_registry_for_tests
from parrot_formdesigner.services.csrf import _clear_csrf_store_for_tests
```

### Existing Signatures to Use

```python
# All exposed in earlier tasks:
# - core/events.py (TASK-1265)
# - services/event_registry.py (TASK-1266)
# - services/event_dispatcher.py (TASK-1267)
# - core/schema.py FormSchema.events (TASK-1268)
# - api/handlers.py read hooks (TASK-1269)
# - api/handlers.py submit hooks (TASK-1270)
# - api/handlers.py + routes.py + services/csrf.py (TASK-1271)
# - renderers/html5.py (TASK-1272)
```

### Does NOT Exist

- ~~Pre-existing CHANGELOG entry for FEAT-188~~ — add one.
- ~~`packages/parrot-formdesigner/docs/lifecycle-events.md`~~ — create.

---

## Implementation Notes

### Doc content outline

```markdown
# Lifecycle Events (FEAT-188)

## Overview
parrot-formdesigner emits five lifecycle hooks per form:
- `onBeforeOpen` — before serving the form (`GET /forms/{id}`).
- `onSchemaLoaded` — after rendering JSON Schema (`GET /forms/{id}/schema`).
- `onBeforeSubmit` — before validating submitted data.
- `onAfterSubmit` — after persistence + forward.
- `onError` — on any exception in the submit pipeline (but NOT `FormEventAbort`).

## Quick start
1. Register a handler:
   ```python
   from parrot_formdesigner.services import register_form_event
   from parrot_formdesigner.core.events import EventResolution

   @register_form_event("survey_v1.onBeforeSubmit", tenant="acme")
   async def normalize_email(ctx):
       payload = dict(ctx.payload)
       payload["email"] = payload["email"].strip().lower()
       return EventResolution(payload=payload)
   ```

2. Declare in the form schema:
   ```python
   from parrot_formdesigner.core.events import FormEventsConfig, FormEventBinding

   form = FormSchema(
       form_id="survey_v1",
       title={"en": "Survey"},
       sections=[...],
       events=FormEventsConfig(
           onBeforeSubmit=FormEventBinding(handler_ref="survey_v1.onBeforeSubmit"),
       ),
   )
   ```

## Cancelling a flow
Raise `FormEventAbort(reason, user_message=..., status_code=...)`.
Aborts are NOT routed through `onError` — they are valid flow control.

## Server vs client
Server-side hooks run in the aiohttp handler. Client-side, the HTML5 renderer
emits `CustomEvent('parrot:<event>', ...)` for the host page to listen to.

If a binding sets `remote: true`, the client additionally fetches
`POST /api/v1/forms/{id}/events/{event}` with the `X-CSRF-Token` issued in
the `GET /forms/{id}` response header.

## Limitations (MVP)
- One handler per `(form, event)` — chain inside the handler if needed.
- `schema_overrides` is shallow-merged.
- CSRF storage is in-process (does not span workers).
- Telegram / AdaptiveCard / PDF / XForms renderers do NOT emit lifecycle events yet.
```

### CHANGELOG entry shape

```markdown
## [Unreleased]
### Added
- **FEAT-188 — Form Lifecycle Events**: declarative interceptor hooks
  (`onBeforeOpen`, `onSchemaLoaded`, `onBeforeSubmit`, `onAfterSubmit`, `onError`)
  per form. Tenant-scoped registry, typed abort exception, HTML5 renderer
  emits `CustomEvent`s + optional `remote: true` fetch with CSRF protection.
  See `docs/lifecycle-events.md`.
```

### Key Constraints

- The e2e tests should NOT mock the registry or dispatcher — they should hit the actual HTTP layer.
- The backward-compat test compares response bodies and headers against a baseline form (no `events`) and asserts byte equality (or near-equality if timestamps differ; in that case, normalize timestamps before compare).

---

## Acceptance Criteria

- [ ] `pytest packages/parrot-formdesigner/tests/integration/test_lifecycle_events_e2e.py -v` all pass.
- [ ] `pytest packages/parrot-formdesigner -v` full suite passes — ZERO regressions.
- [ ] Documentation rendered correctly (mkdocs build or markdown lint, whichever the project uses).
- [ ] CHANGELOG entry exists in `packages/parrot-formdesigner/CHANGELOG.md`.
- [ ] Backward-compat acid test: a form without `events` produces byte-identical `get_form`, `get_schema`, and `submit_data` responses compared to a pre-feature baseline (timestamps normalized).
- [ ] All spec §5 acceptance criteria are satisfied in aggregate.

---

## Test Specification

```python
# tests/integration/test_lifecycle_events_e2e.py
import pytest
from parrot_formdesigner.core.events import (
    EventResolution, FormEventAbort, FormEventBinding, FormEventsConfig,
)
from parrot_formdesigner.services import register_form_event
from parrot_formdesigner.services.event_registry import _clear_event_registry_for_tests
from parrot_formdesigner.services.csrf import _clear_csrf_store_for_tests


@pytest.fixture(autouse=True)
def _clear():
    yield
    _clear_event_registry_for_tests()
    _clear_csrf_store_for_tests()


async def test_full_lifecycle_observed(api_client, form_with_all_hooks):
    invocations = []

    @register_form_event("all.onBeforeOpen")
    async def open_h(ctx):
        invocations.append("open")

    @register_form_event("all.onSchemaLoaded")
    async def schema_h(ctx):
        invocations.append("schema")

    @register_form_event("all.onBeforeSubmit")
    async def before_h(ctx):
        invocations.append("before")
        return EventResolution(payload={**dict(ctx.payload), "_normalized": True})

    @register_form_event("all.onAfterSubmit")
    async def after_h(ctx):
        invocations.append("after")

    @register_form_event("all.onError")
    async def error_h(ctx):
        invocations.append("error")

    # Walk the API endpoints in order:
    await api_client.get(f"/api/v1/forms/{form_with_all_hooks.form_id}")
    await api_client.get(f"/api/v1/forms/{form_with_all_hooks.form_id}/schema")
    resp = await api_client.post(
        f"/api/v1/forms/{form_with_all_hooks.form_id}/data",
        json={"name": "x"},
    )

    assert "open" in invocations
    assert "schema" in invocations
    assert "before" in invocations
    assert "after" in invocations
    # No error path triggered in the happy case:
    assert "error" not in invocations


async def test_backward_compat_form_without_events(api_client, baseline_form):
    """A form with no events declared must produce byte-identical responses."""
    r1 = await api_client.get(f"/api/v1/forms/{baseline_form.form_id}")
    body = await r1.text()
    # Compare against the captured pre-feature golden file in tests/golden/.
    # If exact byte equality is too strict (timestamps), normalize then compare.
```

---

## Agent Instructions

1. **Read the spec** §5 Acceptance Criteria (this is the final-task checklist).
2. **Check dependencies** — all 8 prior tasks must be completed.
3. **Run the full existing suite first** (`pytest packages/parrot-formdesigner`) to confirm no prior regression exists before adding e2e tests.
4. **Implement** — tests first (red), then docs (green-ish), then CHANGELOG.
5. **Verify** every acceptance criterion in spec §5 by walking the list and ticking off.
6. **Move** this file to `sdd/tasks/completed/`.
7. **At this point the feature is complete** — run `/sdd-done FEAT-188`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
