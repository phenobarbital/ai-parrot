---
type: Wiki Summary
title: parrot.auth.oauth2.o365_provider
id: mod:parrot.auth.oauth2.o365_provider
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Office365 OAuth2 provider for the AI-Parrot integrations registry.
relates_to:
- concept: class:parrot.auth.oauth2.o365_provider.O365OAuth2Provider
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.o365_oauth
  rel: references
- concept: mod:parrot.auth.oauth2.registry
  rel: references
- concept: mod:parrot_tools.o365.oauth_toolkit
  rel: references
---

# `parrot.auth.oauth2.o365_provider`

Office365 OAuth2 provider for the AI-Parrot integrations registry.

Wraps :class:`parrot.auth.o365_oauth.O365OAuthManager` and the
:class:`parrot_tools.o365.oauth_toolkit.Office365Toolkit` factory. Register
once at application startup, after the manager is constructed::

    from parrot.auth.o365_oauth import O365OAuthManager
    from parrot.auth.oauth2.registry import register_oauth2_provider
    from parrot.auth.oauth2.o365_provider import O365OAuth2Provider

    manager = O365OAuthManager(client_id=..., client_secret=..., redirect_uri=...,
                               tenant_id=..., app=app)
    manager.setup()
    register_oauth2_provider(O365OAuth2Provider(manager=manager))

## Classes

- **`O365OAuth2Provider(OAuth2Provider)`** — OAuth2 provider for Microsoft Office 365 (delegated / 3LO).
