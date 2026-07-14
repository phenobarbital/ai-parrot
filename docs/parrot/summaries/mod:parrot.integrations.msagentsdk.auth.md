---
type: Wiki Summary
title: parrot.integrations.msagentsdk.auth
id: mod:parrot.integrations.msagentsdk.auth
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-user credential resolver for the Microsoft 365 Agents SDK integration.
relates_to:
- concept: class:parrot.integrations.msagentsdk.auth.BFTokenServiceResolver
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.security.audit_ledger
  rel: references
---

# `parrot.integrations.msagentsdk.auth`

Per-user credential resolver for the Microsoft 365 Agents SDK integration.

Provides :class:`BFTokenServiceResolver`, a :class:`CredentialResolver`
subclass that acquires per-user tokens from the Bot Framework Token Service
(part of the Azure Bot infrastructure). The resolver:

1. Maps a tool name to an Azure Bot OAuth connection name (from config).
2. Fetches the current per-user token from the SDK token client.
3. Records a ``key_fingerprint`` (SHA-256 of the credential material) to an
   :class:`~parrot.security.audit_ledger.AuditLedger` for compliance.

When the token service has no token for the user (sign-in not yet completed),
:meth:`BFTokenServiceResolver.resolve` returns ``None`` so the broker
(:class:`~parrot.auth.broker.CredentialBroker`) can convert the miss to a
:class:`~parrot.auth.credentials.NeedsAuth` signal and raise the canonical
:class:`~parrot.auth.credentials.CredentialRequired` (FEAT-264).

Raw tokens are never returned in a way that exposes them to the model context
or the conversational transcript.

All ``microsoft_agents.*`` imports are kept **inside methods** (lazy) so this
module can be imported without the SDK installed.

## Classes

- **`BFTokenServiceResolver(CredentialResolver)`** — Resolves per-user tokens from the Bot Framework Token Service.
