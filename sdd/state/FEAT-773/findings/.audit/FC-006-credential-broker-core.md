---
id: FC-006
query_id: Q025
type: read
intent: "Broker: read CredentialBroker core — resolve signature, identity mapper, audit, NeedsAuth."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-006 — CredentialBroker (FEAT-264) is a provider_id→(resolver, auth_kind) registry; resolve(provider, channel, user_id) returns ResolvedCredential|NeedsAuth, fails closed, appends audit

## Summary

`parrot/auth/broker/core.py` (252 lines). `CredentialBroker.__init__(*, audit_ledger=None, identity_mapper=None)`; `register(provider, resolver, auth_kind="oauth2")`; `from_config(configs: list[ProviderCredentialConfig], strict=True, **deps)` builds resolvers via `CredentialResolverFactory` (pure, no I/O). `resolve(provider, channel, user_id, **ctx)` raises `ValueError` on empty identity and `KeyError` on unknown provider (fail closed), calls `resolver.resolve(channel, canonical_id)`; on `None` returns `NeedsAuth(provider, auth_url=resolver.get_auth_url(...), auth_kind)`; on hit derives a SHA-256 fingerprint and appends to `parrot.security.audit_ledger.AuditLedger`. Comment at :183-188: surfaces already canonicalise identity before calling, so `identity_mapper` is NOT applied inside resolve.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: 32-79
  symbol: `CredentialBroker`
  excerpt: |
    class CredentialBroker:
        def __init__(self, *, audit_ledger: AuditLedger | None = None, identity_mapper: CanonicalIdentityMapper | None = None)
            self._resolvers: dict[str, tuple[CredentialResolver, str]] = {}
- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: 81-104
  symbol: `CredentialBroker.register`
  excerpt: |
    def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None
- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: 106-154
  symbol: `CredentialBroker.from_config`
  excerpt: |
    @classmethod
    def from_config(cls, configs: list[ProviderCredentialConfig], strict: bool = True, **deps) -> CredentialBroker
- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: 156-215
  symbol: `CredentialBroker.resolve`
  excerpt: |
    async def resolve(self, provider: str, channel: str, user_id: str, **ctx) -> ResolvedCredential | NeedsAuth:
        canonical_id = user_id  # identity_mapper NOT applied here (surfaces canonicalise first)
        if not canonical_id: raise ValueError(...)  # fail closed
        entry = self._resolvers.get(provider)
        if entry is None: raise KeyError(...)
        secret = await resolver.resolve(channel, canonical_id)
        if secret is None: return NeedsAuth(provider=provider, auth_url=await resolver.get_auth_url(channel, canonical_id), auth_kind=auth_kind)

## Notes

This is the closest existing analogue to the brainstorm's `ConnectionManager.get_credentials` + `VaultCredentialResolver`. It does NOT do start/callback/refresh/revoke — those remain in the per-provider managers. Companion files: `broker/factory.py`, `broker/byok.py` (FC-050).
