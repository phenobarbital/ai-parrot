---
id: FC-001
query_id: Q020
type: read
intent: "R2: read CredentialResolver ABC + OAuthCredentialResolver — generic or Jira-typed; signatures (channel, user_id)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-001 — CredentialResolver ABC is generic (channel, user_id); FEAT-264 broker models live beside it

## Summary

`parrot/auth/credentials.py` (246 lines) defines the generic `CredentialResolver` ABC with `resolve(channel, user_id) -> Optional[Any]`, `get_auth_url(channel, user_id)`, `is_connected()`. `OAuthCredentialResolver` is typed to `JiraOAuthManager` only in a TYPE_CHECKING hint; it duck-types any manager exposing `get_valid_token`/`create_authorization_url`. The file also hosts the FEAT-264 broker models: `AuthKind = Literal["obo","oauth2","static_key","mcp","device_code"]`, `ProviderCredentialConfig`, `ResolvedCredential`, `NeedsAuth` (auth_url + device-code fields) and the surface-neutral `CredentialRequired(provider, auth_url, auth_kind, *, user_code, verification_uri, expires_in)` exception. The resolver key is `(channel, user_id)` — channel-scoped, not principal-scoped.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/credentials.py`
  lines: 43
  symbol: `AuthKind`
  excerpt: |
    AuthKind = Literal["obo", "oauth2", "static_key", "mcp", "device_code"]
- path: `packages/ai-parrot/src/parrot/auth/credentials.py`
  lines: 113-154
  symbol: `CredentialRequired`
  excerpt: |
    class CredentialRequired(Exception):
        def __init__(self, provider: str, auth_url: str, auth_kind: str, *, user_code=None, verification_uri=None, expires_in=None)
- path: `packages/ai-parrot/src/parrot/auth/credentials.py`
  lines: 162-181
  symbol: `CredentialResolver`
  excerpt: |
    class CredentialResolver(ABC):
        async def resolve(self, channel: str, user_id: str) -> Optional[Any]
        async def get_auth_url(self, channel: str, user_id: str) -> str
        async def is_connected(self, channel: str, user_id: str) -> bool
- path: `packages/ai-parrot/src/parrot/auth/credentials.py`
  lines: 184-202
  symbol: `OAuthCredentialResolver`
  excerpt: |
    def __init__(self, oauth_manager: "JiraOAuthManager")
    async def resolve(...): return await self._manager.get_valid_token(channel, user_id)
    async def get_auth_url(...): url, _ = await self._manager.create_authorization_url(channel, user_id)
- path: `packages/ai-parrot/src/parrot/auth/credentials.py`
  lines: 82-110
  symbol: `NeedsAuth`
  excerpt: |
    class NeedsAuth(BaseModel):
        provider: str; auth_url: str; auth_kind: AuthKind; user_code; verification_uri; expires_in

## Notes

Brainstorm §3 row 'CredentialResolver ABC … generic or Jira-typed' → generic. Two 'needs auth' signals coexist in core: `AuthorizationRequired` (auth/exceptions.py) and `CredentialRequired` (here). Resolver API is channel-keyed, which is exactly the shape the brainstorm wants to replace with a principal key.
