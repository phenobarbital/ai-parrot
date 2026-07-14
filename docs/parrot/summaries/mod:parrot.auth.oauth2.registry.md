---
type: Wiki Summary
title: parrot.auth.oauth2.registry
id: mod:parrot.auth.oauth2.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OAuth2 provider registry.
relates_to:
- concept: class:parrot.auth.oauth2.registry.OAuth2Provider
  rel: defines
- concept: class:parrot.auth.oauth2.registry.OAuth2ProviderRegistry
  rel: defines
- concept: func:parrot.auth.oauth2.registry.register_oauth2_provider
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.tools
  rel: references
---

# `parrot.auth.oauth2.registry`

OAuth2 provider registry.

Defines the ``OAuth2Provider`` abstract base class and the
``OAuth2ProviderRegistry`` in-memory singleton.  Providers register themselves
at application startup via :func:`register_oauth2_provider`.

## Classes

- **`OAuth2Provider(ABC)`** — Abstract base class for an OAuth2-capable provider.
- **`OAuth2ProviderRegistry`** — In-memory singleton registry of :class:`OAuth2Provider` instances.

## Functions

- `def register_oauth2_provider(provider: OAuth2Provider) -> None` — Module-level convenience for application startup.
