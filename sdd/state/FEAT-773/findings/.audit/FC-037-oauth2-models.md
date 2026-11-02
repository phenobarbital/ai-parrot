---
id: FC-037
query_id: Q026-F1
type: read
intent: "Follow-up: read parrot/auth/oauth2/models.py — the existing integration/connection data models."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-007
depth: 1
---

# FC-037 — oauth2/models.py already defines the API contracts the brainstorm proposes: IntegrationDescriptor, ConnectInitRequest/Response (auth_url, state, scopes, expires_in), DisconnectResponse, AuthRequiredEnvelope, UsersIntegrationRow (user_id, provider, channel, status, account_id, display_name, scopes, cloud_id, site_url, connected_at, last_used_at)

## Summary

201 lines. `IntegrationDescriptor(provider, display_name, icon, default_scopes, connected, status: IntegrationStatus, enabled_on_agent, account_id, display_account_name, email, connected_at)`; `ConnectInitRequest(return_origin)`; `ConnectInitResponse(auth_url, state, scopes, expires_in=600)`; `EnableResponse(integration)`; `DisconnectResponse(provider, disconnected=True)`; `AuthRequiredEnvelope(type="auth_required", provider, tool_name, auth_url, scopes, message)`; `UsersIntegrationRow(user_id, provider, channel="web", status: active|revoked, account_id, display_name, email, scopes, cloud_id, site_url, connected_at, last_used_at)`; `UserAgentToolkitRow(user_id, agent_id, toolkit_id, provider, enabled_at)`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/models.py`
  lines: 21-51
  symbol: `IntegrationDescriptor`
  excerpt: |
    class IntegrationDescriptor(BaseModel):
        provider: str; display_name: str; icon; default_scopes: List[str]; connected: bool = False; status: Optional[IntegrationStatus]; enabled_on_agent: bool; account_id; display_account_name; email; connected_at
- path: `packages/ai-parrot/src/parrot/auth/oauth2/models.py`
  lines: 79-92
  symbol: `ConnectInitResponse`
  excerpt: |
    class ConnectInitResponse(BaseModel):
        auth_url: str; state: str; scopes: List[str]; expires_in: int = 600
- path: `packages/ai-parrot/src/parrot/auth/oauth2/models.py`
  lines: 117-139
  symbol: `AuthRequiredEnvelope`
  excerpt: |
    type: Literal["auth_required"] = "auth_required"; provider: str; tool_name; auth_url; scopes; message: str
- path: `packages/ai-parrot/src/parrot/auth/oauth2/models.py`
  lines: 147-180
  symbol: `UsersIntegrationRow`
  excerpt: |
    user_id: str; provider: str; channel: str = "web"; status: Literal["active","revoked"]; account_id: str; display_name: str; email; scopes: List[str]; cloud_id; site_url; connected_at; last_used_at

## Notes

Brainstorm §5 items 1 & 7 (`Connection`, `ConnectionStatus`, `/connections` response) map almost 1:1 onto these. `UsersIntegrationRow` is the metadata row (no tokens), keyed `(user_id, provider)` — principal-keyed, with `channel` as an attribute.
