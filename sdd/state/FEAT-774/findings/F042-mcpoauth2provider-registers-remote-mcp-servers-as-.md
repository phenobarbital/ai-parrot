---
id: F042
query_id: Q010
type: wiki_page
intent: "Read the wiki page of the MCP OAuth2 provider in parrot.auth.oauth2 (what 'mcp' auth_kind means for the broker)."
executed_at: 2026-10-30T15:23:00Z
duration_ms: 800
parent_id: null
depth: 1
merged_from: [FW-007]
---

# F042 — `MCPOAuth2Provider` registers remote MCP servers as `mcp:{server_name}` providers in the unified `OAuth2ProviderRegistry`

## Summary

`parrot/auth/oauth2/mcp_provider.py` defines `MCPOAuth2Provider(OAuth2Provider)` with `provider_id = "mcp:{server_name}"`, `display_name = "MCP: {server_name}"`, `default_scopes` from the `MCPOAuth2Config`, `pbac_action_namespace = "integration"`, a `manager` property returning the underlying OAuth manager, and `toolkit_factory(credential_resolver)` returning `None` (tools arrive via MCP itself). `register_mcp_oauth2_provider(server_name, config, storage)` registers it globally so `IntegrationsService.list_for_user` lists remote MCP servers next to O365/Jira. This is the bridge between the S-1 connections core and remote MCP servers: once S-1 lands, an MCP remote is already a "provider" a principal can connect; S-4's local stdio servers are the inverse direction (parrot tools consumed by an external host), which this module does not cover.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  lines: 1-20
  symbol: module docstring
  excerpt: |
    Registers MCP OAuth2 servers in the unified ``OAuth2ProviderRegistry`` so that
    IntegrationsService.list_for_user returns them alongside O365, Jira, and other providers.
    MCP tools arrive via the MCP protocol itself — the ``toolkit_factory`` returns ``None``
- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  lines: 24-33
  symbol: imports
  excerpt: |
    from parrot.auth.oauth2.registry import OAuth2Provider, register_oauth2_provider
    from parrot.mcp.oauth2_config import MCPOAuth2Config
    if TYPE_CHECKING: from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  symbol: `MCPOAuth2Provider`
  excerpt: |
    class MCPOAuth2Provider(OAuth2Provider):
        provider_id "mcp:{server_name}"; display_name "MCP: {server_name}"; pbac_action_namespace "integration"
        def __init__(self, server_name, config, storage) / def manager(self) / def toolkit_factory(self, credential_resolver) -> None
- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  symbol: `register_mcp_oauth2_provider`
  excerpt: |
    def register_mcp_oauth2_provider(server_name, config, storage): Create an MCPOAuth2Provider and register it in the global registry.

## Notes

Wiki page `file:packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py` (module). Note `list_for_user` is the pre-S-1 name; S-1 M6 renames it `list_for_principal` — S-4's spec must cite the post-S-1 name.
