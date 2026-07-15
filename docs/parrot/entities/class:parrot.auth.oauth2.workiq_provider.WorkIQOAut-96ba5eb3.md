---
type: Wiki Entity
title: WorkIQOAuth2Provider
id: class:parrot.auth.oauth2.workiq_provider.WorkIQOAuth2Provider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OAuth2 provider for Work IQ (Microsoft) — Entra delegated OBO flow.
relates_to:
- concept: class:parrot.auth.oauth2.registry.OAuth2Provider
  rel: extends
---

# WorkIQOAuth2Provider

Defined in [`parrot.auth.oauth2.workiq_provider`](../summaries/mod:parrot.auth.oauth2.workiq_provider.md).

```python
class WorkIQOAuth2Provider(OAuth2Provider)
```

OAuth2 provider for Work IQ (Microsoft) — Entra delegated OBO flow.

Work IQ is an MCP-based Microsoft enterprise assistant that applies M365
permissions, sensitivity labels, and compliance policies automatically.
Access requires admin consent for
``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.

This provider is a thin wrapper that:
- Carries Work IQ provider metadata (``provider_id``, ``display_name``,
  ``default_scopes``) for the :class:`~parrot.auth.oauth2.registry.OAuth2ProviderRegistry`.
- Holds a pre-built :class:`WorkIQOBOCredentialResolver` returned by
  :meth:`credential_resolver`.

Registration::

    register_oauth2_provider(WorkIQOAuth2Provider(...))
    a2a_server.wire_workiq_resolver(provider.credential_resolver())

Attributes:
    provider_id: Always ``"workiq"``.
    display_name: ``"Work IQ"``.
    icon: Material Design Icon key ``"mdi:microsoft"``.
    default_scopes: Work IQ delegated OBO scope list.
    pbac_action_namespace: ``"integration"``.

## Methods

- `def manager(self) -> Any` — Return the underlying O365 OAuth manager.
- `def credential_resolver(self) -> WorkIQOBOCredentialResolver` — Return the pre-built :class:`WorkIQOBOCredentialResolver`.
- `def toolkit_factory(self, credential_resolver: Any) -> Any` — Not implemented — Work IQ is MCP-based, no native toolkit.
