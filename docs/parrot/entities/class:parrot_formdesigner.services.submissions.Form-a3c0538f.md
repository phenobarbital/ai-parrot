---
type: Wiki Entity
title: FormSubmission
id: class:parrot_formdesigner.services.submissions.FormSubmission
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Record of a single form data submission.
---

# FormSubmission

Defined in [`parrot_formdesigner.services.submissions`](../summaries/mod:parrot_formdesigner.services.submissions.md).

```python
class FormSubmission(BaseModel)
```

Record of a single form data submission.

Attributes:
    submission_id: Unique identifier for this submission.
    form_id: ID of the form that was submitted.
    form_version: Version of the form at the time of submission.
    data: The validated (sanitized) submission data.
    is_valid: Whether the submission passed form validation.
    forwarded: Whether the submission was forwarded to an external endpoint.
    forward_status: HTTP status code from the forwarding request (if any).
    forward_error: Error message from failed forwarding (if any).
    created_at: UTC timestamp when the submission was created.
    tenant: Optional tenant slug. When set, ``FormSubmissionStorage``
        uses it to resolve the Postgres schema where the submission
        is stored. ``None`` falls back to the storage's default
        schema.
    user_id: Promoted metadata column — authenticated user identifier.
    username: Promoted metadata column — authenticated username.
    org_id: Promoted metadata column — authenticated organization ID.
    submitted_at: Promoted metadata column — wall-clock moment the
        form left the client. Distinct from ``created_at`` (which is
        the DB-insert moment).
    ip: Promoted metadata column — submitter IP address.
    user_agent: Promoted metadata column — submitter User-Agent header.
    locale: Promoted metadata column — BCP-47 locale (e.g. ``en-US``).
