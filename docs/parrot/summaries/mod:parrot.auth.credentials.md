---
type: Wiki Summary
title: parrot.auth.credentials
id: mod:parrot.auth.credentials
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Credential resolution abstractions for toolkits.
relates_to:
- concept: class:parrot.auth.credentials.CredentialRequired
  rel: defines
- concept: class:parrot.auth.credentials.CredentialResolver
  rel: defines
- concept: class:parrot.auth.credentials.NeedsAuth
  rel: defines
- concept: class:parrot.auth.credentials.OAuthCredentialResolver
  rel: defines
- concept: class:parrot.auth.credentials.ProviderCredentialConfig
  rel: defines
- concept: class:parrot.auth.credentials.ResolvedCredential
  rel: defines
- concept: class:parrot.auth.credentials.StaticCredentialResolver
  rel: defines
- concept: class:parrot.auth.credentials.StaticCredentials
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
---

# `parrot.auth.credentials`

Credential resolution abstractions for toolkits.

:class:`CredentialResolver` is the bridge between a toolkit and its
credential storage.  It hides whether credentials come from a static
configuration (legacy basic auth / PAT) or from a per-user OAuth 2.0
token store backed by Redis, allowing toolkits to simply call
``resolver.resolve(channel, user_id)`` without knowing the scheme.

Two concrete resolvers are provided:

- :class:`OAuthCredentialResolver`: delegates to a :class:`JiraOAuthManager`
  (or any object that exposes ``get_valid_token`` / ``create_authorization_url``).
- :class:`StaticCredentialResolver`: always returns the same
  :class:`StaticCredentials` — used for the existing ``basic_auth`` and
  ``token_auth`` modes so legacy toolkits keep working unchanged.

FEAT-264 additions
------------------
- :class:`ProviderCredentialConfig` — declarative per-provider credential config
  (AgentDefinition / manifest).
- :class:`ResolvedCredential` — credential material resolved from vault (secret
  never logged; only the ``key_fingerprint`` is recorded in the audit ledger).
- :class:`NeedsAuth` — surface-neutral miss signal returned by the broker.
- :class:`CredentialRequired` — exception raised by the tool-loop seam when the
  broker returns ``NeedsAuth``; surfaces catch it to render their UX.

## Classes

- **`ProviderCredentialConfig(BaseModel)`** — Declarative per-provider credential config (AgentDefinition / manifest).
- **`ResolvedCredential(BaseModel)`** — Credential material returned by the broker on a successful resolution.
- **`NeedsAuth(BaseModel)`** — Surface-neutral miss signal from the broker.
- **`CredentialRequired(Exception)`** — Raised by the tool-loop seam when the broker returns :class:`NeedsAuth`.
- **`CredentialResolver(ABC)`** — Resolves credentials for a given channel/user pair.
- **`OAuthCredentialResolver(CredentialResolver)`** — Resolves credentials from an OAuth 2.0 token store.
- **`StaticCredentials`** — Credential bundle for non-OAuth (legacy) toolkit modes.
- **`StaticCredentialResolver(CredentialResolver)`** — Returns a fixed :class:`StaticCredentials` instance.
