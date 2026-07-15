---
type: Wiki Summary
title: parrot.integrations.telegram.auth
id: mod:parrot.integrations.telegram.auth
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Telegram user authentication — strategies and session management.
relates_to:
- concept: class:parrot.integrations.telegram.auth.AbstractAuthStrategy
  rel: defines
- concept: class:parrot.integrations.telegram.auth.AzureAuthStrategy
  rel: defines
- concept: class:parrot.integrations.telegram.auth.BasicAuthStrategy
  rel: defines
- concept: class:parrot.integrations.telegram.auth.CompositeAuthStrategy
  rel: defines
- concept: class:parrot.integrations.telegram.auth.NavigatorAuthClient
  rel: defines
- concept: class:parrot.integrations.telegram.auth.OAuth2AuthStrategy
  rel: defines
- concept: class:parrot.integrations.telegram.auth.TelegramUserSession
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.core.auth.oauth2_providers
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.integrations.telegram.auth`

Telegram user authentication — strategies and session management.

Provides an abstract auth strategy interface with concrete implementations
for Navigator Basic Auth, Azure AD SSO, OAuth2 (Authorization Code + PKCE),
and a Composite multi-method router (CompositeAuthStrategy) introduced by
FEAT-109 for mixed-identity deployments.

## Classes

- **`TelegramUserSession`** — Cached identity for a Telegram user within a chat session.
- **`NavigatorAuthClient`** — Authenticate Telegram users against Navigator API.
- **`AbstractAuthStrategy(ABC)`** — Base class for Telegram authentication strategies.
- **`BasicAuthStrategy(AbstractAuthStrategy)`** — Navigator Basic Auth strategy.
- **`AzureAuthStrategy(AbstractAuthStrategy)`** — Navigator Azure AD SSO strategy.
- **`OAuth2AuthStrategy(AbstractAuthStrategy)`** — OAuth2 Authorization Code strategy with PKCE.
- **`CompositeAuthStrategy(AbstractAuthStrategy)`** — Multi-method auth router.
