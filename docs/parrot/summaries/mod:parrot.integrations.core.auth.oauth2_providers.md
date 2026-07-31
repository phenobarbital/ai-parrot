---
type: Wiki Summary
title: parrot.integrations.core.auth.oauth2_providers
id: mod:parrot.integrations.core.auth.oauth2_providers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 provider registry for integration authentication flows.
relates_to:
- concept: class:parrot.integrations.core.auth.oauth2_providers.OAuth2ProviderConfig
  rel: defines
- concept: func:parrot.integrations.core.auth.oauth2_providers.get_provider
  rel: defines
---

# `parrot.integrations.core.auth.oauth2_providers`

OAuth2 provider registry for integration authentication flows.

Defines provider configurations (authorization URLs, token endpoints, etc.)
for OAuth2-based login flows. Adding a new provider requires only a new
entry in the OAUTH2_PROVIDERS dict.

This module was lifted from ``parrot.integrations.telegram.oauth2_providers``
to ``parrot.integrations.core.auth.oauth2_providers`` so that all integrations
(Telegram, Slack, MS Teams) can share the same provider catalog.

## Classes

- **`OAuth2ProviderConfig`** — Configuration for a specific OAuth2 identity provider.

## Functions

- `def get_provider(name: str) -> OAuth2ProviderConfig` — Look up an OAuth2 provider by name.
