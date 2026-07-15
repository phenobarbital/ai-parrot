---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.config
id: mod:parrot_tools.interfaces.gigsmart.config
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GigSmart configuration — credentials and API settings.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.config.GigSmartConfig
  rel: defines
- concept: mod:parrot_tools.interfaces.gigsmart.exceptions
  rel: references
---

# `parrot_tools.interfaces.gigsmart.config`

GigSmart configuration — credentials and API settings.

Loads OAuth credentials and endpoint URLs from environment variables.
The ``GigSmartConfig`` Pydantic model is the single source of truth for all
client configuration; other modules receive it by dependency injection.

Environment variables:
    GIGSMART_CLIENT_ID:     OAuth 2.1 client identifier (required)
    GIGSMART_CLIENT_SECRET: OAuth 2.1 client secret (required)
    GIGSMART_ENV:           ``"production"`` (default) or ``"sandbox"``
    GIGSMART_ENDPOINT_URL:  Override the GraphQL endpoint URL
    GIGSMART_LOG_PII:       Set to ``"1"`` to enable PII in log output
    GIGSMART_REFRESH_TOKEN: Pre-configured OAuth refresh token (optional)
    GIGSMART_REQUEST_TIMEOUT: Per-request timeout in seconds (default 30.0)
    GIGSMART_MAX_CONCURRENT_REQUESTS: Max parallel requests, must be >= 1 (default 8)

## Classes

- **`GigSmartConfig(BaseModel)`** — Configuration for the GigSmart API client.
