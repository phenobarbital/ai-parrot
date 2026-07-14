---
type: Wiki Summary
title: parrot_tools.massive.client
id: mod:parrot_tools.massive.client
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async REST client for Massive (ex-Polygon.io).
relates_to:
- concept: class:parrot_tools.massive.client.MassiveAPIError
  rel: defines
- concept: class:parrot_tools.massive.client.MassiveClient
  rel: defines
- concept: class:parrot_tools.massive.client.MassiveRateLimitError
  rel: defines
- concept: class:parrot_tools.massive.client.MassiveTransientError
  rel: defines
---

# `parrot_tools.massive.client`

Async REST client for Massive (ex-Polygon.io).

Directly connects to https://api.massive.com using httpx, 
providing retry logic and rate limit handling.

## Classes

- **`MassiveAPIError(Exception)`** — Base error for Massive API calls.
- **`MassiveRateLimitError(MassiveAPIError)`** — Rate limit exceeded (429).
- **`MassiveTransientError(MassiveAPIError)`** — Transient error (5xx, timeouts).
- **`MassiveClient`** — Async REST client for Massive API with retry and rate limit handling.
