---
type: Wiki Summary
title: parrot.auth.broker
id: mod:parrot.auth.broker
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Surface-agnostic CredentialBroker and CredentialResolverFactory (FEAT-264).
relates_to:
- concept: class:parrot.auth.broker.CredentialBroker
  rel: defines
- concept: class:parrot.auth.broker.CredentialBrokerConfigError
  rel: defines
- concept: class:parrot.auth.broker.CredentialResolverFactory
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.identity
  rel: references
- concept: mod:parrot.auth.oauth2.o365_devicecode_provider
  rel: references
- concept: mod:parrot.auth.oauth2.workiq_provider
  rel: references
- concept: mod:parrot.integrations.mcp.fireflies_a2a
  rel: references
- concept: mod:parrot.security.audit_ledger
  rel: references
---

# `parrot.auth.broker`

Surface-agnostic CredentialBroker and CredentialResolverFactory (FEAT-264).

The :class:`CredentialBroker` owns a ``provider_id → resolver`` registry built
once from declarative :class:`~parrot.auth.credentials.ProviderCredentialConfig`
entries (per-agent config or an in-package YAML manifest).

The :class:`CredentialResolverFactory` maps an ``auth`` kind
(``obo | oauth2 | static_key | mcp``) to a fully-constructed
:class:`~parrot.auth.credentials.CredentialResolver` strategy so that adding
a new provider on an existing auth kind requires only a config entry.

Design principles
-----------------
* **One signal, N renderers** — the broker returns
  :class:`~parrot.auth.credentials.ResolvedCredential` on success or
  :class:`~parrot.auth.credentials.NeedsAuth` on a miss.  It never renders
  UX; surfaces own card / link generation.
* **Secret hygiene** — the raw secret lives only on
  :class:`~parrot.auth.credentials.ResolvedCredential` and never enters the
  broker's logs.  Only the ``key_fingerprint`` is recorded in the audit ledger.
* **Fail-closed** — no resolver for a provider → ``KeyError``; no identity
  → caller must fail closed; ``resolver.resolve() is None`` → ``NeedsAuth``.
* **Pure construction** — :meth:`CredentialBroker.from_config` is synchronous
  and performs no I/O so it is safe to call from ``AbstractBot.configure()``.

## Classes

- **`CredentialBrokerConfigError(Exception)`** — Raised by :meth:`CredentialBroker.from_config` in strict mode when a
- **`CredentialResolverFactory`** — Maps ``auth`` kind to a constructed :class:`CredentialResolver` strategy.
- **`CredentialBroker`** — Surface-agnostic per-user credential broker.
