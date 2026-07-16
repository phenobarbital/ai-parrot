---
type: Wiki Summary
title: parrot.a2a.push_notifications
id: mod:parrot.a2a.push_notifications
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Push notification configuration store for the A2A v1.0 server (FEAT-272).
relates_to:
- concept: class:parrot.a2a.push_notifications.PushNotificationStore
  rel: defines
- concept: mod:parrot.a2a.models
  rel: references
---

# `parrot.a2a.push_notifications`

Push notification configuration store for the A2A v1.0 server (FEAT-272).

Implements the storage/CRUD side of the four A2A v1.0 push-notification config
operations (Create/Get/List/Delete). Actual webhook *delivery* (HTTP POST to
client URLs) is intentionally out of scope — this store only manages the
configuration objects. A basic SSRF guard rejects obviously private/loopback
webhook targets.

## Classes

- **`PushNotificationStore`** — In-memory store for :class:`TaskPushNotificationConfig` objects.
