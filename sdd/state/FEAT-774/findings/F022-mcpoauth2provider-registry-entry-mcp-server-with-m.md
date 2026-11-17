---
id: F022
query_id: Q035
type: read
intent: "MCP OAuth2 provider in parrot.auth.oauth2"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-022]
---

# F022 — MCPOAuth2Provider: registry entry 'mcp:<server>' with manager=None, toolkit_factory=None

## Summary

`MCPOAuth2Provider(server_name, config, storage=None)` registers an MCP server in the unified `OAuth2ProviderRegistry` as `mcp:{server_name}` so `IntegrationsService.list_for_user` lists it; `manager` returns None (flow driven by the MCP SDK at transport level) and `toolkit_factory` returns None. `register_mcp_oauth2_provider()` is the startup helper.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  lines: 36-83, 89-99, 125-152
  symbol: `MCPOAuth2Provider / register_mcp_oauth2_provider`
  excerpt: |
    class MCPOAuth2Provider(OAuth2Provider):
        def __init__(self, server_name: str, config: MCPOAuth2Config, storage: Optional["VaultMCPTokenStorage"] = None)
            self.provider_id: str = f"mcp:{server_name}"
        @property
        def manager(self) -> Any: return None
    def register_mcp_oauth2_provider(server_name, config, storage=None) -> MCPOAuth2Provider:

## Notes

S-1's `DescriptorOAuth2Provider` and this class coexist in the same registry; a connection to a remote MCP server is a provider like any other from the API's point of view.
