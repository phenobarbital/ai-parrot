---
id: FC-053
query_id: Q026-F5
type: read
intent: "Follow-up: oauth2/__init__ exports, JiraOAuth2Provider and MCPOAuth2Provider descriptors."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-007
depth: 1
---

# FC-053 — oauth2/__init__ re-exports models, registry, JiraOAuth2Provider, IntegrationsService; JiraOAuth2Provider wraps JiraOAuthManager; MCPOAuth2Provider registers MCP servers as mcp:{server_name} so they appear in list_for_user (toolkit_factory -> None)

## Summary

`oauth2/__init__.py` imports from `.models`, `.registry`, `.jira_provider`, `.service`. `jira_provider.py` (95): `JiraOAuth2Provider(OAuth2Provider)` `provider_id="jira"`, `display_name="Jira"`, `toolkit_factory(credential_resolver)` → `JiraToolkit(credential_resolver=...)` (ValueError if None). `mcp_provider.py` (152): `MCPOAuth2Provider(server_name, config: MCPOAuth2Config, ...)` with `provider_id = f"mcp:{server_name}"`, `manager` property, `toolkit_factory` returns None ('MCP tools arrive via the MCP protocol itself'); helper `register_mcp_oauth2_provider(server_name, cfg)`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/jira_provider.py`
  lines: 21-95
  symbol: `JiraOAuth2Provider`
  excerpt: |
    class JiraOAuth2Provider(OAuth2Provider):
        provider_id: str = "jira"; display_name: str = "Jira"
        def __init__(self, manager: JiraOAuthManager)
        def toolkit_factory(self, credential_resolver) -> JiraToolkit
- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  lines: 36-125
  symbol: `MCPOAuth2Provider`
  excerpt: |
    class MCPOAuth2Provider(OAuth2Provider):
        self.provider_id: str = f"mcp:{server_name}"
        def toolkit_factory(...) -> None  # MCP tools arrive via the MCP protocol itself
    def register_mcp_oauth2_provider(server_name: str, config: MCPOAuth2Config, ...)

## Notes

MCP servers already participate in the unified provider registry (`mcp:{name}`), so `/connections`-style enumeration across toolkits AND MCP servers is partially in place.
