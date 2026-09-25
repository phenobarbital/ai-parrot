---
id: F003
query_id: Q003
type: wiki_query
intent: Orient: where Hooba credentials should be resolved from (CredentialBroker).
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — CredentialBroker + a ready adapter already turn a provider name into an authenticate credential, failing closed

## Summary

`parrot/auth/broker.py::CredentialBroker` (FEAT-264) is the sanctioned secret source; FEAT-453 added `_credential_resolver_from_broker(broker, user_id)` in `business_automation/toolkit.py` which adapts `broker.resolve(provider, channel, user_id)` into the scraping `CredentialResolverFn` shape, returning `(username, password)` from a dict/tuple secret or `(None, secret)` for an opaque key, and `None` (fail closed) on `NeedsAuth`/errors. `docs/business-automation-runbook.md` §2a documents broker-backed login. The local example instead resolves `HOOBA_USERNAME`/`HOOBA_PASSWORD` from navconfig (F007).

## Citations


- path: `packages/ai-parrot/src/parrot/auth/broker.py`
  lines: 51, 276-326
  symbol: `CredentialBroker, _VaultStaticKeyResolver, _MCPVaultResolver`
  excerpt: |
    class CredentialBroker:  # 326 (per sdd/state/FEAT-453/findings/F010)

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py`
  lines: 52-125
  symbol: `_credential_resolver_from_broker`
  excerpt: |
    async def _resolve(action):
        result = await broker.resolve(action.credential_provider, _BROKER_INVOCATION_CHANNEL, user_id)
        ... if isinstance(result, NeedsAuth): return None
        secret = result.secret
        if isinstance(secret, dict): return secret.get("username"), secret.get("password")

- path: `sdd/state/FEAT-453/findings/F010-credential-broker-and-audit.md`
  lines: 1-60
  symbol: `finding digest`
  excerpt: |
    A surface-agnostic CredentialBroker with vault storage and a signed invocation ledger already exists

- path: `docs/business-automation-runbook.md`
  lines: 58
  symbol: `§2a`
  excerpt: |
    Broker-backed login and mid-plan human pauses
