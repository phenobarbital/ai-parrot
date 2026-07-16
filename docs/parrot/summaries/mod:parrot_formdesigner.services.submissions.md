---
type: Wiki Summary
title: parrot_formdesigner.services.submissions
id: mod:parrot_formdesigner.services.submissions
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form submission persistence service.
relates_to:
- concept: class:parrot_formdesigner.services.submissions.FormSubmission
  rel: defines
- concept: class:parrot_formdesigner.services.submissions.FormSubmissionStorage
  rel: defines
- concept: mod:parrot_formdesigner.services._identifiers
  rel: references
---

# `parrot_formdesigner.services.submissions`

Form submission persistence service.

Provides the ``FormSubmission`` Pydantic model and ``FormSubmissionStorage``
class for persisting form submission records to a PostgreSQL table.
Storage is local-first — data is always saved before optional forwarding
to external endpoints.

Schema, table name, and tenant are configurable. The default schema is
``navigator`` (NOT ``public``) and the default table is ``form_data``
(renamed from the original ``form_submissions``). Pass ``tenant`` at
construction or per-call to target a per-tenant schema such as
``epson.form_data``.

## Classes

- **`FormSubmission(BaseModel)`** — Record of a single form data submission.
- **`FormSubmissionStorage`** — Persist form submissions in a PostgreSQL table.
