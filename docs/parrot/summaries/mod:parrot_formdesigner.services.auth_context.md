---
type: Wiki Summary
title: parrot_formdesigner.services.auth_context
id: mod:parrot_formdesigner.services.auth_context
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Runtime authentication context for per-request credential resolution.
relates_to:
- concept: class:parrot_formdesigner.services.auth_context.AuthContext
  rel: defines
---

# `parrot_formdesigner.services.auth_context`

Runtime authentication context for per-request credential resolution.

This module defines `AuthContext`, the runtime auth context constructed by
the aiohttp handler on each request. It is distinct from `core.auth.AuthConfig`
(the schema-side declaration) — `AuthContext` carries resolved credentials
and is passed explicitly to `OptionsLoader.fetch()`,
`RemoteResponseResolver.resolve()`, and renderers.

Cascade behaviour: the same `AuthContext` instance flows into nested GROUP
and ARRAY field rendering without re-resolution.

## Classes

- **`AuthContext(BaseModel)`** — Runtime auth context constructed by the aiohttp handler per request.
