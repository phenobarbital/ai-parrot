---
id: FC-033
query_id: Q047
type: read
intent: "S-1 spec contracts S-4 must implement"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-033 — S-1 Principal/PrincipalResolver/ConnectionEvent/AuthRequiredPayload shapes; channel enum includes cli

## Summary

S-1 (FEAT-773 spec rev 0.2) fixes the contracts: `Principal(user_id: str  # Navigator bigint as str, canonical_identity, tenant_id, channel: web|telegram|slack|msteams|a2a|cli, channel_user_id)`; `OAuth2ProviderDescriptor` (no device-authorization endpoint field); `ConnectionEvent` kinds completed/revoked/refresh_failed with `channel`; `AuthRequiredPayload` superset incl. `auth_kind: oauth2|device_code|obo|static_key|mcp`, `user_code`, `verification_uri`, `expires_in`; `UsersIntegrationRow` keyed `(user_id, provider)` with `canonical_identity`. Integration table shows `mcp/client.py` M9 (`user_id` optional, broker injection) and `IdentityPrincipalResolver` reading `auth.user_identities` via `IdentityStore` (server).

## Citations

- path: `sdd/specs/delegated-auth-connections.spec.md`
  lines: 229-236
  symbol: `Principal (M1)`
  excerpt: |
    class Principal(BaseModel):
        user_id: str                       # Navigator auth.users.user_id (bigint, serialized as str)
        canonical_identity: Optional[str]  # Entra OID or lower-cased e-mail
        tenant_id: Optional[str] = None
        channel: str                       # originating channel: web | telegram | slack | msteams | a2a | cli
        channel_user_id: str

- path: `sdd/specs/delegated-auth-connections.spec.md`
  lines: 250-265
  symbol: `OAuth2ProviderDescriptor (M3)`
  excerpt: |
    class OAuth2ProviderDescriptor(BaseModel):
        provider_id: str; authorization_url: str; token_url: str; revoke_url: Optional[str] = None
        default_scopes: List[str]; client_type: Literal["confidential", "public"] = "confidential"
        pkce: Literal["required", "optional", "none"] = "required"; refresh_policy: RefreshPolicy
        # client_id / client_secret / redirect_uri come from navconfig OAUTH2_<PROVIDER>_*, never from the descriptor

- path: `sdd/specs/delegated-auth-connections.spec.md`
  lines: 283-293
  symbol: `AuthRequiredPayload (M5)`
  excerpt: |
    class AuthRequiredPayload(BaseModel):
        provider: str; auth_url: Optional[str] = None; scopes: List[str] = []; tool_name: Optional[str] = None
        message: str = ""; auth_kind: Optional[AuthKind] = None
        user_code: Optional[str] = None; verification_uri: Optional[str] = None; expires_in: Optional[int] = None

- path: `sdd/specs/delegated-auth-connections.spec.md`
  lines: 213, 219
  symbol: `Integration table rows (M9, M8)`
  excerpt: |
    | `parrot/mcp/client.py::MCPClientConfig`, ... | modifies | `user_id` optional; per-call principal via broker injection |
    | `ai-parrot-server services/identity_mapping.py::IdentityMappingService` | uses | `IdentityPrincipalResolver` reads `auth.user_identities` through `IdentityStore` |


## Notes

Gaps S-4 must fill vs S-1: a `device_authorization_url` on descriptors (if generic device code is wanted); a CLI `PrincipalResolver`; a client-side `CredentialStore`/resolver speaking to `/api/v1/connections*`.
