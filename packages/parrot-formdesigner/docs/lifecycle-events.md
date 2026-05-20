# Form Lifecycle Events (FEAT-188)

## Overview

parrot-formdesigner emits five lifecycle hooks per form, allowing server-side
code to intercept, mutate, or abort form operations without modifying the
handler pipeline.

| Hook | When it fires | API endpoint |
|---|---|---|
| `onBeforeOpen` | Before serving the form schema | `GET /forms/{id}` |
| `onSchemaLoaded` | After rendering JSON Schema | `GET /forms/{id}/schema` |
| `onBeforeSubmit` | Before validating submitted data | `POST /forms/{id}/data` |
| `onAfterSubmit` | After persistence + forwarding | `POST /forms/{id}/data` |
| `onError` | On any unhandled exception in the submit pipeline | `POST /forms/{id}/data` |

`onError` is **NOT** invoked for `FormEventAbort` — aborts are valid flow
control, not errors.

---

## Quick Start

### 1. Register a handler

```python
from parrot_formdesigner.services import register_form_event
from parrot_formdesigner.core.events import EventResolution

@register_form_event("survey_v1.onBeforeSubmit", tenant="acme")
async def normalize_email(ctx):
    payload = dict(ctx.payload)
    payload["email"] = payload["email"].strip().lower()
    return EventResolution(payload=payload)
```

Handler references follow the pattern `<form_id>.<event_name>` (optionally
tenant-scoped — see *Tenant Scoping* below).

### 2. Declare in the form schema

```python
from parrot_formdesigner.core.events import FormEventsConfig, FormEventBinding
from parrot_formdesigner.core.schema import FormSchema

form = FormSchema(
    form_id="survey_v1",
    title={"en": "Survey"},
    sections=[...],
    events=FormEventsConfig(
        onBeforeSubmit=FormEventBinding(handler_ref="survey_v1.onBeforeSubmit"),
    ),
)
```

Forms without an `events` field behave exactly as they did before FEAT-188 —
zero overhead, byte-identical HTTP responses.

---

## Event Reference

### `FormEventContext`

Every handler receives a `FormEventContext` instance as its only argument:

| Attribute | Type | Description |
|---|---|---|
| `event` | `str` | Name of the event (e.g., `"onBeforeSubmit"`) |
| `form_id` | `str` | Identifier of the form |
| `tenant` | `str` | Resolved tenant |
| `auth_context` | `AuthContext` | Auth info extracted from the request |
| `payload` | `dict | None` | Submitted data (submit events only) |
| `schema_dump` | `dict | None` | Rendered JSON Schema (onSchemaLoaded only) |
| `error` | `Exception | None` | The exception that triggered onError |

### `EventResolution`

Handlers return an `EventResolution` to communicate back to the framework:

```python
from parrot_formdesigner.core.events import EventResolution

return EventResolution(
    payload={"email": "cleaned@example.com"},  # replaces submitted payload
    schema_overrides={"title": "Overridden title"},  # for onSchemaLoaded
    user_message="Something went wrong",  # surface to the caller on error
)
```

All fields are optional with sensible defaults.

### Cancelling a flow with `FormEventAbort`

```python
from parrot_formdesigner.core.events import FormEventAbort

raise FormEventAbort(
    "too_many_attempts",      # machine-readable reason
    user_message="Slow down", # returned in the HTTP JSON body
    status_code=429,          # HTTP status (default 403)
)
```

`FormEventAbort` is **never** routed through `onError`.

---

## onBeforeSubmit — payload replacement

Return a new `payload` in `EventResolution` to replace the submitted data
before validation:

```python
@register_form_event("invoice.onBeforeSubmit")
async def add_tenant_id(ctx):
    data = dict(ctx.payload)
    data["tenant_id"] = ctx.tenant
    return EventResolution(payload=data)
```

---

## onSchemaLoaded — schema overrides

Return `schema_overrides` to shallowly merge top-level keys into the
rendered JSON Schema:

```python
@register_form_event("invoice.onSchemaLoaded")
async def add_tenant_title(ctx):
    return EventResolution(schema_overrides={"title": f"Invoice ({ctx.tenant})"})
```

Overrides are applied at the top level only (shallow merge).

---

## Server-side vs Client-side

### Server-side

All five hooks run in the aiohttp handler synchronously with the request.
Register handlers at application startup.

### Client-side (HTML5 renderer)

When a form has lifecycle events, the HTML5 renderer automatically injects an
inline `<script>` block that emits DOM `CustomEvent`s at the same lifecycle
points:

| JS event | Fires when |
|---|---|
| `parrot:before-open` | `DOMContentLoaded` |
| `parrot:before-submit` | Form submit (cancelable via `event.preventDefault()`) |

Host pages can listen for these events on the form element:

```javascript
document.getElementById('parrot-form-survey_v1')
  .addEventListener('parrot:before-submit', (e) => {
    console.log('Submitting:', e.detail.payload);
  });
```

### Remote bridge (`remote: true`)

When a binding declares `remote: true`, the HTML5 client additionally sends
the event to the server via `fetch`:

```python
events=FormEventsConfig(
    onBeforeSubmit=FormEventBinding(
        handler_ref="survey_v1.onBeforeSubmit",
        remote=True,
    ),
)
```

The browser includes an `X-CSRF-Token` header obtained from the
`X-Form-CSRF-Token` response header on `GET /forms/{id}`.  The server
validates this token before dispatching the event.

---

## CSRF on the Remote Endpoint

`GET /forms/{id}` emits `X-Form-CSRF-Token: <token>` in the response headers
when the form has at least one `remote: true` binding **and** the request has
a valid session.

`POST /forms/{id}/events/{event_name}` requires:
1. A valid `X-CSRF-Token` (or `X-Form-CSRF-Token`) header.
2. The token must match the one issued for the same `(session, form)` pair.
3. The `event_name` must be one of the five valid lifecycle event names.

Requests that fail validation return HTTP 403.

---

## Tenant Scoping

Handler references may be registered globally or for a specific tenant:

```python
# Global (all tenants)
@register_form_event("survey_v1.onBeforeSubmit")
async def global_handler(ctx): ...

# Tenant-specific (checked first)
@register_form_event("survey_v1.onBeforeSubmit", tenant="acme")
async def acme_handler(ctx): ...
```

At dispatch time, the tenant-specific handler is preferred if it exists.

---

## Known Limitations (MVP)

- **One handler per `(form, event[, tenant])`** — if you need multiple
  operations, compose them inside a single handler.
- **`schema_overrides` is shallow** — only top-level keys are merged.  Nested
  override support is a post-MVP follow-up.
- **CSRF storage is in-process** — tokens are stored in a dictionary inside the
  process.  In a multi-worker deployment (e.g., gunicorn with multiple
  processes), tokens issued by worker A will not be visible to worker B.
  Replace `services/csrf.py`'s `_STORE` with a Redis backend for production
  multi-worker setups.
- **HTML5 renderer only** — Telegram, AdaptiveCard, PDF, and XForms renderers
  do not emit lifecycle events.  Client-side `CustomEvent` support for those
  renderers is a post-MVP item.
