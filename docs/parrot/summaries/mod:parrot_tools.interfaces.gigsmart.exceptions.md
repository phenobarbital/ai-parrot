---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.exceptions
id: mod:parrot_tools.interfaces.gigsmart.exceptions
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Typed exception hierarchy for GigSmart API errors.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartAuthError
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartConflictError
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartGraphQLError
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartNotFoundError
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartRateLimitError
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartTransportError
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartValidationError
  rel: defines
---

# `parrot_tools.interfaces.gigsmart.exceptions`

Typed exception hierarchy for GigSmart API errors.

Follows the ``MassiveAPIError`` pattern from ``parrot_tools/massive/client.py``.
Maps to the GraphQL error classification table in the spec (§7).

## Classes

- **`GigSmartError(Exception)`** — Base exception for all GigSmart API errors.
- **`GigSmartAuthError(GigSmartError)`** — Authentication or authorisation failure.
- **`GigSmartValidationError(GigSmartError)`** — Input validation failure.
- **`GigSmartRateLimitError(GigSmartError)`** — Rate limit exceeded (HTTP 429 / ``RATE_LIMITED`` extension code).
- **`GigSmartNotFoundError(GigSmartError)`** — Requested resource does not exist.
- **`GigSmartTransportError(GigSmartError)`** — Network or server-side transport failure.
- **`GigSmartGraphQLError(GigSmartError)`** — Generic GraphQL protocol error.
- **`GigSmartConflictError(GigSmartError)`** — Conflict with the current resource state.
