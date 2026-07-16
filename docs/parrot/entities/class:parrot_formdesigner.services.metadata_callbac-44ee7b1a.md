---
type: Wiki Entity
title: MetadataCallbackInput
id: class:parrot_formdesigner.services.metadata_callbacks.MetadataCallbackInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Payload delivered to a registered metadata-callback coroutine.
---

# MetadataCallbackInput

Defined in [`parrot_formdesigner.services.metadata_callbacks`](../summaries/mod:parrot_formdesigner.services.metadata_callbacks.md).

```python
class MetadataCallbackInput(BaseModel)
```

Payload delivered to a registered metadata-callback coroutine.

Attributes:
    form_id: ID of the form being submitted.
    submission_id: UUID of the in-flight submission (not yet stored).
    user_id: Authenticated user ID (may be ``None``).
    username: Authenticated username (may be ``None``).
    org_id: Authenticated organization ID (may be ``None``).
    tenant: Tenant slug (may be ``None``).
    programs: Tenant programs list (may be empty).
    submitted_at: UTC timestamp of the submission.
    answers: Sanitized form answers as produced by the validator.
        The callback MUST treat this dict as read-only.
    field: The ``FormMetadataField`` declaration that triggered this
        invocation. Carries ``options`` / ``default`` for the
        callback to honour.
