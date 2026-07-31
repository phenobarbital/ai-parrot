---
type: Wiki Summary
title: parrot.integrations.core.auth
id: mod:parrot.integrations.core.auth
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared authentication primitives for AI-Parrot integrations.
relates_to:
- concept: mod:parrot.integrations.core.auth.oauth2_providers
  rel: references
- concept: mod:parrot.integrations.core.auth.post_auth
  rel: references
---

# `parrot.integrations.core.auth`

Shared authentication primitives for AI-Parrot integrations.

This subpackage provides provider-agnostic post-auth protocol abstractions
shared across Telegram, Slack, and MS Teams integrations.

Exports:
    PostAuthProvider: Protocol for secondary authentication providers.
    PostAuthRegistry: Registry mapping provider names to PostAuthProvider instances.
    OAuth2ProviderConfig: Configuration dataclass for OAuth2 identity providers.
    OAUTH2_PROVIDERS: Built-in provider catalog (google, etc.).
    get_provider: Look up a provider by name from the catalog.
