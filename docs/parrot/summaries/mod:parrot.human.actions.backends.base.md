---
type: Wiki Summary
title: parrot.human.actions.backends.base
id: mod:parrot.human.actions.backends.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class and exception hierarchy for escalation action backends.
relates_to:
- concept: class:parrot.human.actions.backends.base.ActionBackend
  rel: defines
- concept: class:parrot.human.actions.backends.base.ActionBackendError
  rel: defines
- concept: class:parrot.human.actions.backends.base.EmailBackendError
  rel: defines
- concept: class:parrot.human.actions.backends.base.NotifyBackendError
  rel: defines
- concept: class:parrot.human.actions.backends.base.WebhookBackendError
  rel: defines
- concept: class:parrot.human.actions.backends.base.ZammadBackendError
  rel: defines
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.actions.backends.base`

Abstract base class and exception hierarchy for escalation action backends.

FEAT-194 — TASK-1275

## Classes

- **`ActionBackendError(Exception)`** — Base exception raised by any ActionBackend on failure.
- **`EmailBackendError(ActionBackendError)`** — Raised when the email backend fails to send a message.
- **`NotifyBackendError(ActionBackendError)`** — Raised when the async-notify backend fails to deliver a notification.
- **`ZammadBackendError(ActionBackendError)`** — Raised when the Zammad backend fails to create a ticket.
- **`WebhookBackendError(ActionBackendError)`** — Raised when the webhook backend fails to post to the endpoint.
- **`ActionBackend(ABC)`** — Abstract base class for concrete escalation action backends.
