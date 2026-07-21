---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.client
id: mod:parrot_tools.interfaces.gigsmart.client
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GigSmart GraphQL client — aiohttp-based transport with retry and error classification.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.client.GigSmartClient
  rel: defines
- concept: mod:parrot_tools.interfaces.gigsmart.auth
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.config
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.exceptions
  rel: references
---

# `parrot_tools.interfaces.gigsmart.client`

GigSmart GraphQL client — aiohttp-based transport with retry and error classification.

Features:
- GraphQL POST via aiohttp.ClientSession with OAuth 2.1 header injection
- Error classification: maps ``extensions.code`` to typed exceptions
- Relay auto-pagination: fetch all nodes from a paginated connection
- Retry with exponential backoff for transient errors (5xx, 429)
- Concurrency limiting via asyncio.Semaphore
- PII scrubbing in log output (controlled by config.log_pii)

## Classes

- **`GigSmartClient`** — aiohttp-based GraphQL client for the GigSmart API.
