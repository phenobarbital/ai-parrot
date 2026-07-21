---
type: Wiki Summary
title: parrot_formdesigner.services.forwarder
id: mod:parrot_formdesigner.services.forwarder
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Submission forwarding service.
relates_to:
- concept: class:parrot_formdesigner.services.forwarder.ForwardResult
  rel: defines
- concept: class:parrot_formdesigner.services.forwarder.SubmissionForwarder
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
---

# `parrot_formdesigner.services.forwarder`

Submission forwarding service.

Sends validated form submission data to the external URL configured in a
``SubmitAction`` using ``aiohttp.ClientSession``. Authentication headers are
resolved at forwarding time via ``AuthConfig.resolve()`` — credentials are
never stored in the form schema.

The ``forward()`` method never raises — it always returns a ``ForwardResult``.

## Classes

- **`ForwardResult(BaseModel)`** — Result of a submission forwarding attempt.
- **`SubmissionForwarder`** — Forward form submission data to configured SubmitAction endpoints.
