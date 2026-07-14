---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.auth
id: mod:parrot_tools.interfaces.gigsmart.auth
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GigSmart OAuth 2.1 authentication — token lifecycle management.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.auth.GigSmartAuth
  rel: defines
- concept: mod:parrot_tools.interfaces.gigsmart.config
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.exceptions
  rel: references
---

# `parrot_tools.interfaces.gigsmart.auth`

GigSmart OAuth 2.1 authentication — token lifecycle management.

Supports two grant types:

* **client_credentials** (server-to-server) — read-only scopes, 15 min tokens.
  Tokens are obtained via HTTP Basic auth to ``/oauth/token``.
* **auth_code + PKCE** (user-facing) — full read+write access, 1 h tokens.
  Requires a user authorisation step; exchange code at ``/oauth/token`` with
  ``code_verifier``.

Pre-configured refresh tokens (from ``GIGSMART_REFRESH_TOKEN``) allow headless
agents to obtain write access without an interactive OAuth flow.

Token caching is in-memory; an ``asyncio.Lock`` prevents concurrent refreshes.
Write-scope enforcement raises ``GigSmartAuthError`` when a write operation is
attempted with a token that only has read scopes.

## Classes

- **`GigSmartAuth`** — OAuth 2.1 token lifecycle manager for the GigSmart API.
