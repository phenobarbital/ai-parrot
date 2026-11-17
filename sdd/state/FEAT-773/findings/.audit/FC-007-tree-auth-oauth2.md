---
id: FC-007
query_id: Q026
type: tree
intent: "Registry: list parrot/auth/oauth2 provider package (base provider + concrete providers)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-007 — parrot/auth/oauth2/ holds models, registry, service (IntegrationsService), persistence and five provider descriptors (jira, o365, o365_devicecode, workiq, mcp)

## Summary

10 source files, 2027 lines: `__init__.py` (57), `models.py` (201), `registry.py` (136), `service.py` (532), `persistence.py` (191), `jira_provider.py` (95), `o365_provider.py` (75), `o365_devicecode_provider.py` (281), `workiq_provider.py` (307), `mcp_provider.py` (152). Sibling `parrot/auth/broker/`: `core.py`, `factory.py`, `byok.py`, `__init__.py`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/registry.py`
  lines: 1-136
  symbol: `module`
  excerpt: |
    OAuth2Provider ABC + OAuth2ProviderRegistry singleton + register_oauth2_provider()
- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: 1-532
  symbol: `module`
  excerpt: |
    IntegrationsService — orchestrates registry, persistence, PBAC
- path: `packages/ai-parrot/src/parrot/auth/oauth2/models.py`
  lines: 1-201
  symbol: `module`
  excerpt: |
    IntegrationDescriptor, ConnectInitRequest/Response, EnableResponse, DisconnectResponse, AuthRequiredEnvelope, UsersIntegrationRow, UserAgentToolkitRow
- path: `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py`
  lines: 1-191
  symbol: `module`
  excerpt: |
    users_integrations / user_agent_toolkits DocumentDB upserts keyed (user_id, provider)
- path: `packages/ai-parrot/src/parrot/auth/broker/factory.py`
  lines: 1-264
  symbol: `module`
  excerpt: |
    CredentialResolverFactory — auth_kind → resolver strategy

## Notes

The brainstorm's proposed `OAuthProviderRegistry` / provider descriptor already exists as `OAuth2ProviderRegistry` + `OAuth2Provider` subclasses (see FC-037/038/039/040/053).
