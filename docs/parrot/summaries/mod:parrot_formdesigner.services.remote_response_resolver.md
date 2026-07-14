---
type: Wiki Summary
title: parrot_formdesigner.services.remote_response_resolver
id: mod:parrot_formdesigner.services.remote_response_resolver
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RemoteResponseResolver service for REMOTE_RESPONSE field type.
relates_to:
- concept: class:parrot_formdesigner.services.remote_response_resolver.RemoteResponseResolver
  rel: defines
- concept: class:parrot_formdesigner.services.remote_response_resolver.RemoteResponseResult
  rel: defines
- concept: class:parrot_formdesigner.services.remote_response_resolver.RemoteResponseSpec
  rel: defines
- concept: mod:parrot_formdesigner.services.auth_context
  rel: references
---

# `parrot_formdesigner.services.remote_response_resolver`

RemoteResponseResolver service for REMOTE_RESPONSE field type.

Calls an external API on behalf of a ``REMOTE_RESPONSE`` form field and
returns the API response as the field value. Mirrors ``SubmissionForwarder``
pattern from ``services/forwarder.py``.

No memoisation — every call hits the endpoint. Callers must ensure endpoint
idempotency when repeated calls are a concern.

## Classes

- **`RemoteResponseSpec(BaseModel)`** — Configuration for a REMOTE_RESPONSE field embedded in ``FormField.meta``.
- **`RemoteResponseResult(BaseModel)`** — Result of a ``RemoteResponseResolver.resolve()`` call.
- **`RemoteResponseResolver`** — Resolve REMOTE_RESPONSE fields by calling an external API.
