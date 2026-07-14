---
type: Wiki Summary
title: parrot.auth.oauth2_base
id: mod:parrot.auth.oauth2_base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generic OAuth 2.0 / PKCE manager for AI-Parrot toolkits.
relates_to:
- concept: class:parrot.auth.oauth2_base.AbstractOAuth2Manager
  rel: defines
- concept: class:parrot.auth.oauth2_base.AbstractOAuth2TokenSet
  rel: defines
- concept: mod:parrot.auth.oauth2_routes
  rel: references
- concept: mod:parrot.security.vault_utils
  rel: references
---

# `parrot.auth.oauth2_base`

Generic OAuth 2.0 / PKCE manager for AI-Parrot toolkits.

Provides :class:`AbstractOAuth2Manager`, a reusable parallel of
:class:`parrot.auth.jira_oauth.JiraOAuthManager` from which any provider
(Office365, GitHub, Slack, …) can inherit. Concrete subclasses only need
to implement the four provider-specific hooks
(``_exchange_code``, ``_refresh_request``, ``_discover_identity``,
``_build_token_set``); the base class handles:

- Authorization URL generation with CSRF state nonces and optional PKCE
  ``code_verifier`` / ``code_challenge``.
- Token persistence in two layers: navigator-session vault (encrypted,
  long-lived) as source of truth + Redis (TTL-bounded) as hot cache.
- Distributed-lock-protected refresh so concurrent requests do not race
  on rotating refresh tokens.
- aiohttp setup/cleanup wiring.

The Jira-specific manager intentionally stays untouched (decision from
the planning phase) — this module is a parallel surface.

## Classes

- **`AbstractOAuth2TokenSet(BaseModel)`** — Provider-agnostic OAuth 2.0 token set.
- **`AbstractOAuth2Manager(ABC)`** — OAuth 2.0 lifecycle manager — provider-agnostic base.
