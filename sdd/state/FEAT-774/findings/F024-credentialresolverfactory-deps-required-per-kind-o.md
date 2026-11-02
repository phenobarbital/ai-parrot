---
id: F024
query_id: Q037
type: read
intent: "Broker factory deps per auth kind"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-024]
---

# F024 — CredentialResolverFactory: deps required per kind (oauth_manager / vault / o365_*)

## Summary

`CredentialResolverFactory(deps).build(cfg)` dispatches on `cfg.auth`: `obo` needs `o365_interface, o365_oauth_manager, vault`; `oauth2` needs `oauth_manager` or `oauth_managers[provider]` → `OAuthCredentialResolver(manager)`; `static_key` needs `vault`; `mcp` → `_MCPVaultResolver(vault, vault_key, auth_url)`; `device_code` needs `o365_client|o365_interface, o365_oauth_manager, vault` → O365 resolver. Every kind except `oauth2` requires a `VaultTokenSync`-like `vault` dep; `oauth2` requires an in-process `AbstractOAuth2Manager` (Redis + CredentialStore under S-1).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/broker/factory.py`
  lines: 46-76
  symbol: `CredentialResolverFactory.build`
  excerpt: |
    if kind == "obo": return self._build_obo(cfg, opts)
    if kind == "oauth2": return self._build_oauth2(cfg, opts)
    if kind == "static_key": return self._build_static_key(cfg, opts)
    if kind == "mcp": return self._build_mcp(cfg, opts)
    if kind == "device_code": return self._build_device_code(cfg, opts)
- path: `packages/ai-parrot/src/parrot/auth/broker/factory.py`
  lines: 114-127
  symbol: `_build_oauth2`
  excerpt: |
    manager = self._deps.get("oauth_manager") or self._deps.get("oauth_managers", {}).get(cfg.provider)
    return OAuthCredentialResolver(manager)
- path: `packages/ai-parrot/src/parrot/auth/broker/factory.py`
  lines: 249-264
  symbol: `_MCPVaultResolver`
  excerpt: |
    class _MCPVaultResolver(CredentialResolver):
        async def resolve(self, channel, user_id): tokens = await self._vault.read_tokens(user_id); return tokens.get(self._vault_key)

## Notes

For an out-of-process CLI/stdio server, S-4 needs either a `CredentialResolver` that talks to the server API (new kind or a remote `oauth_manager`-shaped object) — none exists.
