---
id: F042
query_id: Q025-F1
type: read
intent: "Follow-up: read parrot/auth/identity.py (CanonicalIdentityMapper) and broker/factory.py (resolver strategies)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-006
depth: 1
merged_from: [FC-050]
---

# F042 — CanonicalIdentityMapper.to_canonical(raw) -> Entra OID -> lower-cased email -> None (fail closed); CredentialResolverFactory builds obo|oauth2|static_key|mcp|device_code strategies from ProviderCredentialConfig + deps, plus a BYOK user LLM-key resolver

## Summary

`auth/identity.py` (148 lines): OID fields `oid`, `aad_object_id`, …; email fields `email`, `upn`, `from_email`, `from.email`, `x-ms-user-email`, `sender`; static `to_canonical(raw_identity: Dict) -> Optional[str]`. `auth/broker/factory.py` (264 lines): `CredentialResolverFactory(deps)`, `build(cfg)` dispatches on `cfg.auth` to `_build_obo` (:82), `_build_oauth2` (:114), `_build_static_key` (:129), `_build_mcp` (:155), `_build_device_code` (:167); `build_user_llm_key_resolver()` (:202, BYOK); private `_VaultStaticKeyResolver(vault, vault_key, capture_url)` and `_MCPVaultResolver(vault, vault_key, auth_url)`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/identity.py`
  lines: 57-100
  symbol: `CanonicalIdentityMapper`
  excerpt: |
    class CanonicalIdentityMapper:
        @staticmethod
        def to_canonical(raw_identity: Dict[str, Any]) -> Optional[str]  # OID -> email -> None
- path: `packages/ai-parrot/src/parrot/auth/broker/factory.py`
  lines: 11-71
  symbol: `CredentialResolverFactory.build`
  excerpt: |
    if kind == "obo": return self._build_obo(cfg, opts)
    if kind == "oauth2": return self._build_oauth2(cfg, opts)
    if kind == "static_key": ...
    if kind == "mcp": ...
    if kind == "device_code": ...
- path: `packages/ai-parrot/src/parrot/auth/broker/factory.py`
  lines: 222-264
  symbol: `_VaultStaticKeyResolver / _MCPVaultResolver`
  excerpt: |
    class _VaultStaticKeyResolver(CredentialResolver): __init__(self, vault, vault_key, capture_url)
    class _MCPVaultResolver(CredentialResolver): __init__(self, vault, vault_key, auth_url)

## Notes

Canonical identity today = Entra OID or email (Copilot/A2A surfaces), NOT the navigator-auth bigint user_id used by Telegram/Teams/web — two competing principal notions the proposal must reconcile.
