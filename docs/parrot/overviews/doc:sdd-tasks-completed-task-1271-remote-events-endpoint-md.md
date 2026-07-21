---
type: Wiki Overview
title: 'TASK-1271: Remote events endpoint with CSRF protection'
id: doc:sdd-tasks-completed-task-1271-remote-events-endpoint-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements §3 Module 6. Provides the server-side endpoint that the HTML5
  renderer (TASK-1272) calls when a binding declares `remote: true`. This endpoint
  must validate a per-form CSRF token in addition to the standard auth via `_wrap_auth`.'
---

# TASK-1271: Remote events endpoint with CSRF protection

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1267, TASK-1268, TASK-1270
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 6. Provides the server-side endpoint that the HTML5 renderer (TASK-1272) calls when a binding declares `remote: true`. This endpoint must validate a per-form CSRF token in addition to the standard auth via `_wrap_auth`.

---

## Scope

- Add a new handler method `FormAPIHandler.remote_event` that:
  - Validates the URL `event_name` is in `FormEventName` (400 if not).
  - Loads the form (404 if missing).
  - Reads the `X-CSRF-Token` header; validates against a per-session per-form token (401/403 if missing or invalid).
  - Parses the JSON body for `payload` / `schema_dump` / `extra` (whatever the event needs).
  - Calls `dispatch(event_name, ...)`.
  - Returns the `EventResolution` serialized to JSON.
  - Catches `FormEventAbort` → typed JSON response.
- Register the route in `setup_form_api` (api/routes.py:85):
  `app.router.add_post(f"{bp}/forms/{{form_id}}/events/{{event_name}}", _wrap_auth(handler.remote_event))`.
- Implement the CSRF token mechanism:
  - Issue a token in `get_form` response header (e.g., `X-Form-CSRF-Token`) tied to `(session_id, form_id)`.
  - Validate the token in `remote_event` — token must match the issued one for the same `(session, form)`.
  - Use an in-process keyed dict with a soft TTL (e.g., 1h) for MVP; document the storage decision in the task completion note. The spec defers storage details to this task.
- Add tests in `tests/integration/test_lifecycle_events_remote.py`.

**NOT in scope**: HTML5 renderer changes (TASK-1272 consumes the token), e2e docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Add `remote_event` method + CSRF helpers + token emission in `get_form` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Register the new route in `setup_form_api` (l.85) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/csrf.py` | CREATE | Token issue + validate helpers (in-process MVP store) |
| `packages/parrot-formdesigner/tests/integration/test_lifecycle_events_remote.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In api/handlers.py:
from parrot_formdesigner.services.csrf import (  # created by THIS task
    issue_form_csrf_token,
    validate_form_csrf_token,
)
from parrot_formdesigner.core.events import FormEventName, FormEventAbort
from parrot_formdesigner.services.event_dispatcher import dispatch

# typing import for runtime validation of FormEventName:
from typing import get_args
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:
    def _get_tenant(self, request: web.Request) -> str: ...           # line 154
    def _build_auth_context(self, request: web.Request) -> AuthContext: ...  # line 176
    def _extract_session_id(self, request: web.Request) -> str | None: ...
    # ^ session-id helper used by partial saves. Verify exact name with grep before importing.

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:60
def _wrap_auth(handler: _Handler) -> _Handler: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:85
def setup_form_api(app, ...): ...
```

### Does NOT Exist

- ~~`parrot_formdesigner.services.csrf`~~ — create it.
- ~~`issue_form_csrf_token`, `validate_form_csrf_token`~~ — create them.
- ~~Any existing CSRF middleware in the package~~ — confirm via `grep -r "csrf" packages/parrot-formdesigner/src`; do NOT introduce a new dependency on `aiohttp-csrf` etc.

---

## Implementation Notes

### CSRF token (MVP)

```python
# services/csrf.py
import secrets
import time
from typing import Final

_TTL_SECONDS: Final = 3600
# In-process store: {(session_id, form_id): (token, expires_at)}
_STORE: dict[tuple[str, str], tuple[str, float]] = {}


def issue_form_csrf_token(session_id: str, form_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _STORE[(session_id, form_id)] = (token, time.monotonic() + _TTL_SECONDS)
    return token


def validate_form_csrf_token(session_id: str, form_id: str, token: str) -> bool:
    entry = _STORE.get((session_id, form_id))
    if entry is None:
        return False
    stored_token, expires_at = entry
    if time.monotonic() > expires_at:
        _STORE.pop((session_id, form_id), None)
        return False
    return secrets.compare_digest(stored_token, token)


def _clear_csrf_store_for_tests() -> None:
    _STORE.clear()
```

### `remote_event` handler shape

```python
async def remote_event(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]
    event_name = request.match_info["event_name"]

    # 1. Validate event_name
    if event_name not in get_args(FormEventName):
        return web.json_response({"error": f"Unknown event '{event_name}'"}, status=400)

    # 2. Load form (404 if missing)
    tenant = self._get_tenant(request)
    form = await self.registry.get(form_id, tenant=tenant)
    if form is None:
        return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)

    # 3. CSRF
    session_id = self._extract_session_id(request)
    token = request.headers.get("X-CSRF-Token") or request.headers.get("X-Form-CSRF-Token")
    if not session_id or not token or not validate_form_csrf_token(session_id, form_id, token):
        return web.json_response({"error": "CSRF token invalid or missing"}, status=403)

    # 4. Parse body
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    # 5. Dispatch
    try:
        resolution = await dispatch(
            event_name,  # type: ignore[arg-type]
            form=form, request=request,
            tenant=tenant,
            auth_context=self._build_auth_context(request),
            payload=body.get("payload"),
            schema_dump=body.get("schema_dump"),
        )
    except FormEventAbort as exc:
        return web.json_response(
            {"error": exc.user_message, "reason": exc.reason},
            status=exc.status_code,
        )

    return web.json_response(resolution.model_dump(exclude_none=True))
```

### Token issuance in `get_form`

In `get_form` (already touched by TASK-1269), after the form is loaded and `onBeforeOpen` resolves OK, attach the token to the response **only if the form has any `remote: true` binding**:

```python
response = web.json_response(form.model_dump())
if _form_has_remote_binding(form):
    session_id = self._extract_session_id(request)
    if session_id:
        response.headers["X-Form-CSRF-Token"] = issue_form_csrf_token(session_id, form_id)
return response
```

Helper `_form_has_remote_binding`: iterate `form.events.<each>` and return True if any binding has `remote=True`.

### Key Constraints

- The CSRF store is in-process for MVP. If `aiohttp` workers run multi-process (e.g., gunicorn), tokens won't cross workers. Document this limitation in the completion note; production hardening is a follow-up.
- The endpoint MUST go through `_wrap_auth` AND additionally CSRF-check — both layers, not one or the other.
- Pass through `payload` / `schema_dump` from the body verbatim. Do NOT introspect or validate beyond JSON parse — the handler's responsibility.

### References in Codebase

- `api/routes.py:162-198` — pattern for `_wrap_auth(handler.X)` route registration.
- `api/handlers.py:840` `submit_data` — pattern for JSON parse + early returns.

---

## Acceptance Criteria

- [ ] `POST /api/v1/forms/{form_id}/events/{event_name}` route is registered.
- [ ] Request without `X-CSRF-Token` → 403.
- [ ] Request with wrong token → 403.
- [ ] Request with `event_name` not in `FormEventName` → 400.
- [ ] Request with valid CSRF + valid event name + valid handler → dispatch invoked, resolution returned.
- [ ] `get_form` response includes `X-Form-CSRF-Token` header IFF the form has any `remote: true` binding.
- [ ] All new tests pass.
- [ ] `ruff` + `mypy --strict` clean on `services/csrf.py`.

---

## Test Specification

```python
# tests/integration/test_lifecycle_events_remote.py
import pytest
from parrot_formdesigner.services.csrf import _clear_csrf_store_for_tests
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _clear():
    yield
    _clear_event_registry_for_tests()
    _clear_csrf_store_for_tests()


async def test_remote_endpoint_requires_csrf(api_client, form_with_remote_hook):
    resp = await api_client.post(
        f"/api/v1/forms/{form_with_remote_hook.form_id}/events/onBeforeSubmit",
        json={"payload": {}},
    )
    assert resp.status == 403

async def test_remote_endpoint_rejects_invalid_event_name(api_client, csrf_token):
    resp = await api_client.post(
        "/api/v1/forms/any/events/onBogus",
        json={"payload": {}},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status == 400

async def test_remote_endpoint_dispatches_with_csrf(api_client, form_with_remote_hook, csrf_token):
    resp = await api_client.post(
        f"/api/v1/forms/{form_with_remote_hook.form_id}/events/onBeforeSubmit",
        json={"payload": {"x": 1}},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status == 200

async def test_get_form_attaches_csrf_token_when_remote_binding_present(api_client, form_with_remote_hook):
    resp = await api_client.get(f"/api/v1/forms/{form_with_remote_hook.form_id}")
    assert "X-Form-CSRF-Token" in resp.headers
```

---

## Agent Instructions

1. **Read the spec** §3 Module 6 and §7 *Authentication for the remote endpoint*.
2. **Check dependencies** — TASK-1267, TASK-1268, TASK-1270.
3. **Verify the Codebase Contract** — grep for the actual name of the session-id helper (`_extract_session_id` per partial-saves handler context); adjust if different.
4. **Implement** — small in-process CSRF helper + route + handler.
5. **Verify** acceptance criteria.
6. **Move** this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
