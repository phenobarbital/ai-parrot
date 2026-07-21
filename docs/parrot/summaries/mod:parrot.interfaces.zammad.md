---
type: Wiki Summary
title: parrot.interfaces.zammad
id: mod:parrot.interfaces.zammad
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Zammad helpdesk interface via REST API v1.
relates_to:
- concept: class:parrot.interfaces.zammad.TicketCreatePayload
  rel: defines
- concept: class:parrot.interfaces.zammad.TicketUpdatePayload
  rel: defines
- concept: class:parrot.interfaces.zammad.UserCreatePayload
  rel: defines
- concept: class:parrot.interfaces.zammad.ZammadAuthError
  rel: defines
- concept: class:parrot.interfaces.zammad.ZammadConfig
  rel: defines
- concept: class:parrot.interfaces.zammad.ZammadConnectionError
  rel: defines
- concept: class:parrot.interfaces.zammad.ZammadError
  rel: defines
- concept: class:parrot.interfaces.zammad.ZammadInterface
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot.interfaces.zammad`

Zammad helpdesk interface via REST API v1.

Provides an async-first interface to Zammad servers for ticket, user,
article, and attachment operations. Supports Bearer token authentication
and "On Behalf Of" impersonation via a configurable HTTP header.

## Classes

- **`ZammadError(Exception)`** — Base exception for Zammad REST API errors.
- **`ZammadAuthError(ZammadError)`** — Raised when authentication fails (401 response).
- **`ZammadConnectionError(ZammadError)`** — Raised on network or connection failures.
- **`ZammadConfig(BaseModel)`** — Configuration for Zammad API connection.
- **`TicketCreatePayload(BaseModel)`** — Payload for creating a Zammad ticket.
- **`TicketUpdatePayload(BaseModel)`** — Payload for updating a Zammad ticket.
- **`UserCreatePayload(BaseModel)`** — Payload for creating a Zammad user.
- **`ZammadInterface`** — Async interface for Zammad REST API v1.
