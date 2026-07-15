---
type: Wiki Summary
title: parrot.auth.o365_oauth
id: mod:parrot.auth.o365_oauth
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Office 365 (Microsoft Graph) OAuth 2.0 manager with PKCE.
relates_to:
- concept: class:parrot.auth.o365_oauth.O365OAuthManager
  rel: defines
- concept: class:parrot.auth.o365_oauth.O365TokenSet
  rel: defines
- concept: mod:parrot.auth.oauth2_base
  rel: references
---

# `parrot.auth.o365_oauth`

Office 365 (Microsoft Graph) OAuth 2.0 manager with PKCE.

Concrete :class:`parrot.auth.oauth2_base.AbstractOAuth2Manager` for
Microsoft Identity Platform delegated (3LO) auth, supporting both
personal and work/school accounts.

The manager talks directly to ``https://login.microsoftonline.com`` and
``https://graph.microsoft.com`` — it does not depend on MSAL, since the
abstract base already handles the moving parts (PKCE, nonces, refresh
locks, vault persistence). The Graph SDK is only used by the toolkit
when calling actual API endpoints.

## Classes

- **`O365TokenSet(AbstractOAuth2TokenSet)`** — Office 365 token set extension.
- **`O365OAuthManager(AbstractOAuth2Manager)`** — Microsoft Identity Platform OAuth 2.0 (PKCE + client_secret).
