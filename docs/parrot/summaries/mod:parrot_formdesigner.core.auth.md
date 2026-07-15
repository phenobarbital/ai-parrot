---
type: Wiki Summary
title: parrot_formdesigner.core.auth
id: mod:parrot_formdesigner.core.auth
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Authentication configuration models for form submission forwarding.
relates_to:
- concept: class:parrot_formdesigner.core.auth.ApiKeyAuth
  rel: defines
- concept: class:parrot_formdesigner.core.auth.BearerAuth
  rel: defines
- concept: class:parrot_formdesigner.core.auth.NoAuth
  rel: defines
---

# `parrot_formdesigner.core.auth`

Authentication configuration models for form submission forwarding.

This module defines the AuthConfig discriminated union used by SubmitAction
to configure how outbound HTTP requests are authenticated when forwarding
form submissions to external endpoints.

Credentials are always resolved from environment variables at forwarding
time — never stored as raw secrets in the form schema.

## Classes

- **`NoAuth(BaseModel)`** — No authentication — default, backward-compatible.
- **`BearerAuth(BaseModel)`** — Bearer token authentication resolved from an environment variable.
- **`ApiKeyAuth(BaseModel)`** — API key authentication resolved from an environment variable.
