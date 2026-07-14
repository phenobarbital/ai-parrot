---
type: Wiki Entity
title: RestCallbackInput
id: class:parrot_formdesigner.services.rest_field_resolver.RestCallbackInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Payload delivered to a registered callback coroutine.
---

# RestCallbackInput

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class RestCallbackInput(BaseModel)
```

Payload delivered to a registered callback coroutine.

Attributes:
    form_id: ID of the parent form.
    field_id: ID of the field triggering the upload.
    session_id: User session ID (may be ``None``).
    user_id: Authenticated user ID (may be ``None``).
    tenant: Tenant slug (may be ``None``).
    content_type: MIME type of the uploaded content.
    content: Uploaded payload — bytes for binary, str for text, dict for JSON.
    extra_fields: Additional form fields forwarded for context.
