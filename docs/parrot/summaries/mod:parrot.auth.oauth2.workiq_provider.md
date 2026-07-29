---
type: Wiki Summary
title: parrot.auth.oauth2.workiq_provider
id: mod:parrot.auth.oauth2.workiq_provider
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Work IQ OAuth2 provider with Entra On-Behalf-Of (OBO) token exchange.
relates_to:
- concept: class:parrot.auth.oauth2.workiq_provider.WorkIQOAuth2Provider
  rel: defines
- concept: class:parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.oauth2.registry
  rel: references
- concept: mod:parrot.interfaces.o365
  rel: references
---

# `parrot.auth.oauth2.workiq_provider`

Work IQ OAuth2 provider with Entra On-Behalf-Of (OBO) token exchange.

OQ#5 resolved (2026-06-27 — FEAT-263 / TASK-1649):
Work IQ (``github.com/microsoft/work-iq``) is an **MCP server** that supports
delegated Entra OBO authentication.  App-only access is NOT supported.

Required permission: ``WorkIQAgent.Ask`` (delegated, requires admin consent).
OAuth scope: ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.

Work IQ applies M365 permissions, sensitivity labels, and compliance policies
automatically — no additional filtering is required on the adapter side.

OBO flow:
1. User signs in via the o365 / Entra 3LO flow (covered by the existing
   ``O365OAuth2Provider``).  The Entra access token is stored in vault as
   ``o365:access_token``.
2. :class:`WorkIQOBOCredentialResolver` calls
   ``O365Client.acquire_token_on_behalf_of(user_assertion, scopes)`` to
   exchange the Entra token for a Work IQ OBO token.
3. The OBO token is cached in vault as ``workiq:access_token`` and returned
   to the A2A bridge for use with the Work IQ MCP server.

One Entra sign-in covers both o365 and work-iq.

Registration::

    from parrot.auth.oauth2.workiq_provider import WorkIQOAuth2Provider
    from parrot.auth.oauth2.registry import register_oauth2_provider
    from parrot.interfaces.o365 import O365Client

    o365 = O365Client(credentials={...})
    provider = WorkIQOAuth2Provider(
        o365_interface=o365,
        o365_oauth_manager=o365_manager,
        vault_token_sync=vault,
    )
    register_oauth2_provider(provider)
    a2a_server.wire_workiq_resolver(provider.credential_resolver())

## Classes

- **`WorkIQOBOCredentialResolver(CredentialResolver)`** — Credential resolver that exchanges an Entra assertion for a Work IQ OBO token.
- **`WorkIQOAuth2Provider(OAuth2Provider)`** — OAuth2 provider for Work IQ (Microsoft) — Entra delegated OBO flow.
