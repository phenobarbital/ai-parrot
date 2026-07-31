---
type: Wiki Overview
title: 'Brainstorm: MCP Server OAuth2 Support'
id: doc:sdd-proposals-mcp-server-oauth2-support-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot can consume external MCP servers, but authentication support is
  fragmented
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.auth.oauth2.mcp_provider
  rel: mentions
- concept: mod:parrot.auth.oauth2.registry
  rel: mentions
- concept: mod:parrot.auth.oauth2.service
  rel: mentions
- concept: mod:parrot.auth.oauth2_base
  rel: mentions
- concept: mod:parrot.auth.oauth2_routes
  rel: mentions
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.registry
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: MCP Server OAuth2 Support

**Date**: 2026-06-26
**Author**: Claude / Jesus
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot can consume external MCP servers, but authentication support is fragmented
across two independent OAuth2 systems:

1. **`parrot.mcp.oauth.OAuthManager`** — MCP-specific, spins up a local HTTP callback
   server on `localhost:8765`, uses its own `TokenStore` hierarchy
   (`InMemoryTokenStore`, `RedisTokenStore`, `VaultTokenStore`).
2. **`parrot.auth.oauth2_base.AbstractOAuth2Manager`** — general-purpose, uses the
   Navigator app server for callbacks, has provider registry + PBAC + distributed
   lock-protected refresh, with concrete providers for O365 and Jira.

When a user wants to connect to an OAuth2-protected MCP server (e.g., Fireflies.ai,
NetSuite, GitHub MCP, Google MCP), they must either:
- Use `create_oauth_mcp_server()` which spins up a standalone local callback server
  (won't work when Navigator is running), OR
- Manually wire up `AbstractOAuth2Manager` with no MCP integration path.

Meanwhile, the MCP Python SDK v1.23.0 ships its own full OAuth2 implementation
(`mcp.client.auth.oauth2.OAuthClientProvider`) with PKCE, RFC 8414 metadata discovery,
RFC 7591 dynamic client registration, and RFC 8707 resource indicators — none of which
AI-Parrot currently leverages.

**Who is affected:**
- Developers integrating OAuth2-protected MCP servers into their agents.
- End users who need to authorize via browser when an agent first connects to a service.
- Autonomous/server agents that need headless (client_credentials) auth to MCP servers.

---

## Constraints & Requirements

- Must extend `MCPClientConfig` (not a new config type) — user decision.
- Must unify under `parrot.auth.oauth2` — eliminate the parallel `parrot.mcp.oauth.OAuthManager`.
- Must use the MCP SDK's native OAuth2 (`mcp.client.auth.oauth2`) for flow mechanics.
- Must use navigator-auth's vault for token persistence (per-user + per-server scope).
- Browser-based redirect must use the Navigator app server (not a standalone localhost server).
- Must support headless token exchange for autonomous/server agents (client_credentials).
- Must support auto-re-auth on token expiry (transparent retry).
- Must support both YAML presets for known servers and inline config for custom servers.
- Must not break existing `add_perplexity_mcp_server()`, `add_fireflies_mcp_server()` etc.
- Async-first, no blocking I/O.

---

## Options Explored

### Option A: Unified OAuth2 Provider Bridge — MCP SDK Native + Navigator Auth

Create an `MCPOAuth2Provider` that subclasses `OAuth2Provider` (from the existing
registry) and implements the MCP SDK's `TokenStorage` protocol by delegating to the
existing `VaultTokenStore`. The MCP SDK's `OAuthClientProvider` handles the flow
mechanics (PKCE, metadata discovery, dynamic registration), while Navigator handles
the callback and vault persistence.

The `MCPClientConfig` gains an `oauth2` field (a new `MCPOAuth2Config` Pydantic model)
that holds `client_id`, `auth_url`, `token_url`, `scopes`, and an optional `preset`
name. When `preset` is set, defaults are loaded from a presets registry. When
`MCPClientConfig` detects an `oauth2` config, it auto-wires the MCP SDK's OAuth2
provider and sets up the `token_supplier`.

Key insight: adapt MCP SDK's `TokenStorage` protocol to delegate to AI-Parrot's
`VaultTokenStore`, creating a thin `VaultMCPTokenStorage` adapter. This reuses
encrypted vault persistence with zero duplication.

**Pros:**
- Leverages MCP SDK's RFC-compliant OAuth2 (PKCE, metadata discovery, dynamic registration).
- Single auth system — all OAuth2 goes through `parrot.auth.oauth2` provider registry.
- Vault-backed, encrypted token persistence — battle-tested infrastructure.
- Supports both interactive (browser) and headless (client_credentials) flows.
- Presets provide zero-config experience for known servers (Fireflies, GitHub, Google).
- YAML config stays clean — `auth_preset: fireflies` or inline `oauth2:` block.
- Backward-compatible — existing helper methods become thin wrappers.

**Cons:**
- Higher initial complexity: adapter layer between MCP SDK's `TokenStorage` and AI-Parrot's `VaultTokenStore`.
- Must register OAuth2 callback route on Navigator at startup (minor plumbing).
- MCP SDK's OAuth2 uses `httpx` internally, while AI-Parrot uses `aiohttp` — two HTTP clients active during auth flows.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mcp==1.23.0` | MCP SDK OAuth2 client (`OAuthClientProvider`, `TokenStorage`) | Already installed |
| `httpx>=0.27.1` | HTTP client used by MCP SDK internally | Already a dependency |
| `navigator-auth` | Vault (AES-GCM encrypted credential storage) | Already installed |
| `pydantic>=2.11.0` | `MCPOAuth2Config` model, validation | Already installed |

**Existing Code to Reuse:**
- `parrot/mcp/client.py:131` — `MCPClientConfig` (extend with `oauth2` field)
- `parrot/mcp/client.py:15-127` — `AuthScheme`, `AuthCredential` (reuse OAUTH2 scheme)
- `parrot/mcp/oauth.py:70-170` — `VaultTokenStore` (adapt to MCP SDK's `TokenStorage`)
- `parrot/auth/oauth2/registry.py:20-136` — `OAuth2Provider`, `OAuth2ProviderRegistry`
- `parrot/auth/oauth2/service.py:67` — `IntegrationsService` (extend for MCP)
- `parrot/auth/oauth2_base.py:1-80` — `AbstractOAuth2Manager`, `AbstractOAuth2TokenSet`
- `parrot/mcp/integration.py:729-781` — `create_oauth_mcp_server()` (replace internals)
- `parrot/mcp/registry.py:89-122` — `UserMCPServerConfig` (already has `vault_credential_name`)
- `parrot/auth/oauth2_routes.py` — `setup_oauth2_routes()` (extend for MCP callback)

---

### Option B: MCP SDK-Only — Full Delegation to MCP SDK OAuth2

Replace all AI-Parrot OAuth2 handling for MCP with the MCP SDK's built-in
`OAuthClientProvider`. Implement a custom `TokenStorage` that wraps `VaultTokenStore`,
but skip the `OAuth2ProviderRegistry` integration — MCP OAuth2 lives entirely within
the MCP subsystem.

The `MCPClientConfig` gets an `oauth2` field, and when present, the `HttpMCPSession`
passes the MCP SDK's auth provider directly to `httpx`. No Navigator callback route
needed — the MCP SDK handles its own callback server.

**Pros:**
- Simplest implementation — thin glue between MCP SDK and vault.
- MCP SDK manages the full lifecycle (discovery, registration, PKCE, refresh).
- No changes to `parrot.auth.oauth2` at all.

**Cons:**
- Two parallel OAuth2 systems remain (MCP SDK's own + `parrot.auth.oauth2`).
- No PBAC integration for MCP OAuth2 (security gap).
- MCP SDK's callback server conflicts with Navigator on the same port.
- No unified token management dashboard — MCP tokens invisible to `IntegrationsService`.
- Presets harder to implement without the provider registry.
- Duplicate vault adapter code (can't reuse `IntegrationsService.persist_credential()`).

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mcp==1.23.0` | Full OAuth2 lifecycle | Already installed |

**Existing Code to Reuse:**
- `parrot/mcp/client.py:131` — `MCPClientConfig` (extend with `oauth2`)
- `parrot/mcp/oauth.py:70-170` — `VaultTokenStore` (adapt to `TokenStorage`)

---

### Option C: Custom OAuth2 with MCP SDK Discovery — Extend AbstractOAuth2Manager

Keep AI-Parrot's `AbstractOAuth2Manager` as the OAuth2 engine but enhance it with
MCP SDK's metadata discovery (`build_oauth_authorization_server_metadata_discovery_urls`,
`handle_auth_metadata_response`). Create an `MCPOAuth2Manager` subclass of
`AbstractOAuth2Manager` that uses RFC 8414 discovery to auto-configure endpoints.

The MCP SDK's `OAuthClientProvider` is NOT used — only its utility functions for
discovery. Token exchange, PKCE, and refresh are handled by `AbstractOAuth2Manager`.

**Pros:**
- Single OAuth2 system — everything goes through `AbstractOAuth2Manager`.
- Full control over token lifecycle, refresh locking, and vault persistence.
- PBAC, provider registry, and `IntegrationsService` work out of the box.
- Navigator callback route reused from existing O365/Jira flows.

**Cons:**
- Duplicates MCP SDK's OAuth2 flow logic (PKCE, token exchange) instead of using it.
- Must manually implement RFC 7591 dynamic client registration (MCP SDK already has it).
- Must track MCP SDK spec changes and port them manually.
- More code to maintain long-term — AI-Parrot re-implements what the SDK provides.
- MCP SDK's resource indicators (RFC 8707) would need manual implementation.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mcp==1.23.0` | Discovery utilities only | Only `mcp.client.auth.utils` used |
| `navigator-auth` | Vault persistence | Already installed |
| `aiohttp` | HTTP client for token exchange | Already installed |

**Existing Code to Reuse:**
- `parrot/auth/oauth2_base.py` — `AbstractOAuth2Manager` (subclass)
- `parrot/auth/oauth2/registry.py` — `OAuth2ProviderRegistry`
- `parrot/auth/oauth2/service.py` — `IntegrationsService`
- `parrot/auth/oauth2_routes.py` — `setup_oauth2_routes()`
- `parrot/mcp/oauth.py:70-170` — `VaultTokenStore`

---

## Recommendation

**Option A** is recommended because:

It delivers the best of both worlds: the MCP SDK handles the protocol-level OAuth2
mechanics (PKCE, RFC 8414 discovery, RFC 7591 dynamic registration, RFC 8707 resource
indicators) while AI-Parrot's `OAuth2ProviderRegistry` + `IntegrationsService` provide
the orchestration, PBAC, and unified token management that enterprise deployments need.

The key tradeoff vs. Option B is complexity (adapter layer between MCP SDK's
`TokenStorage` and AI-Parrot's vault) — but this is thin, well-bounded code that
eliminates the maintenance burden of two parallel auth systems.

The key tradeoff vs. Option C is that we accept `httpx` as a second HTTP client
during auth flows — but this is already a transitive dependency and only active during
the initial OAuth2 handshake, not on every MCP tool call.

---

## Feature Description

### User-Facing Behavior

**YAML Configuration:**

```yaml
# Preset — zero-config for known servers
mcp_servers:
  - name: fireflies
    auth_preset: fireflies
    # API key prompted on first use, or set via env var

  - name: netsuite
    auth_preset: netsuite
    oauth2:
      client_id: "${NETSUITE_CLIENT_ID}"
      account_id: "${NETSUITE_ACCOUNT_ID}"

# Inline — custom OAuth2 server
  - name: my-custom-server
    url: "https://mcp.example.com/v1"
    oauth2:
      client_id: "my-app"
      client_secret: "${MY_SECRET}"  # optional
      auth_url: "https://auth.example.com/authorize"
      token_url: "https://auth.example.com/token"
      scopes: ["read", "write"]
      grant_type: "authorization_code"  # or "client_credentials"
```

**Programmatic:**

```python
# Using preset
await bot.add_mcp_server("fireflies", auth_preset="fireflies")

# Using inline OAuth2
await bot.add_oauth_mcp_server(
    name="my-server",
    url="https://mcp.example.com/v1",
    client_id="my-app",
    auth_url="https://auth.example.com/authorize",
    token_url="https://auth.example.com/token",
    scopes=["read", "write"],
)
```

**First-use flow:**
1. Agent calls an MCP tool → transport detects no valid token.
2. If interactive: browser opens to authorization URL, user approves,
   callback hits Navigator, token is stored in vault.
3. If headless (client_credentials): token is acquired automatically.
4. Tool call retries transparently.

**Subsequent calls:**
- Token loaded from vault → tool call proceeds.
- If token expired → auto-refresh (if refresh_token) or re-auth.

### Internal Behavior

1. **Config parsing**: `MCPClientConfig.from_yaml_config()` detects `oauth2:` or
   `auth_preset:` keys and constructs an `MCPOAuth2Config` model.
2. **Provider resolution**: If `auth_preset` is set, look up the `MCPOAuth2Preset`
   from the presets registry, merge with any user overrides in `oauth2:`.
3. **Token storage adapter**: `VaultMCPTokenStorage` implements the MCP SDK's
   `TokenStorage` protocol, delegating to `VaultTokenStore` for `get_tokens`/`set_tokens`
   and to DocumentDB for `get_client_info`/`set_client_info`.
4. **OAuth2 provider registration**: An `MCPOAuth2Provider` is registered in
   `OAuth2ProviderRegistry` for each configured MCP server, making it visible to
   `IntegrationsService`.
5. **Transport integration**: `HttpMCPSession.connect()` detects `oauth2` config
   and injects the MCP SDK's `OAuthClientProvider` (or `ClientCredentialsOAuthProvider`
   for M2M) as the httpx auth handler.
6. **Auto-refresh**: The MCP SDK handles token refresh automatically via its
   `OAuthContext`. On 401 responses, the transport triggers re-auth.
7. **Callback route**: A single Navigator route `/api/auth/oauth2/mcp/callback`
   handles all MCP OAuth2 callbacks, dispatching by `state` parameter to the
   correct `OAuthContext`.

### Edge Cases & Error Handling

- **Navigator not running (CLI/standalone)**: Fall back to a temporary local
  callback server (preserve current behavior as degraded mode).
- **Token expired + no refresh_token**: Trigger full re-auth flow.
  Interactive → browser opens. Headless → raise `MCPAuthError` with instructions.
- **OAuth2 server unreachable during discovery**: Raise `MCPConnectionError`
  with clear message. Skip RFC 8414 discovery and fall back to explicit URLs.
- **User denies consent**: Callback receives `error=access_denied`.
  Agent receives `MCPAuthError("User denied authorization")`.
- **Concurrent token refresh**: Handled by MCP SDK's `anyio.Lock` in `OAuthContext`.
  Additional protection from `VaultTokenStore`'s existing distributed lock.
- **Vault unavailable**: Graceful degradation — tokens stored in-memory only,
  warning logged. User re-authorizes on next restart.
- **Multiple users, same MCP server**: Tokens scoped per-user + per-server in
  vault (`mcp_oauth_{server}_{user_id}`). No cross-contamination.

---

## Capabilities

### New Capabilities
- `mcp-oauth2-config`: OAuth2 configuration model for `MCPClientConfig` with preset support
- `mcp-oauth2-presets`: Built-in presets registry for known OAuth2 MCP servers
- `mcp-oauth2-token-adapter`: Bridge between MCP SDK's `TokenStorage` and AI-Parrot's `VaultTokenStore`
- `mcp-oauth2-provider`: `OAuth2Provider` implementation for MCP servers in the unified registry

### Modified Capabilities
- `mcp-client-config`: Extended with `oauth2` and `auth_preset` fields
- `mcp-http-session`: Transport-level integration with MCP SDK's OAuth2 provider
- `oauth2-routes`: Navigator callback route extended for MCP OAuth2 callbacks
- `mcp-server-registry`: `MCPServerDescriptor` extended with `auth_type: oauth2` and preset config

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot.mcp.client.MCPClientConfig` | extends | Add `oauth2: MCPOAuth2Config` and `auth_preset: str` fields |
| `parrot.mcp.oauth` | modifies | Deprecate `OAuthManager`, keep `VaultTokenStore` and token stores |
| `parrot.mcp.integration.MCPClient` | modifies | Wire MCP SDK OAuth2 provider into transport setup |
| `parrot.mcp.integration.MCPEnabledMixin` | modifies | Update `add_oauth_mcp_server()` and factory functions |
| `parrot.auth.oauth2.registry` | extends | New `MCPOAuth2Provider` registered for each MCP server |
| `parrot.auth.oauth2_routes` | extends | Add `/api/auth/oauth2/mcp/callback` route |
| `parrot.mcp.registry` | extends | Add `auth_type` field to `MCPServerDescriptor` |
| `mcp.client.auth.oauth2` | depends on | MCP SDK's `OAuthClientProvider`, `TokenStorage` protocol |
| `HttpMCPSession` (ai-parrot-server) | modifies | Inject OAuth2 auth handler into httpx session |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/mcp/client.py:15
class AuthScheme(str, Enum):
    OAUTH2 = "oauth2"  # line 20

# From parrot/mcp/client.py:130
@dataclass
class MCPClientConfig:
    name: str                                            # line 155
    url: Optional[str] = None                            # line 158
    auth_credential: Optional[AuthCredential] = None     # line 167
    auth_type: Optional[AuthScheme] = None               # line 168
    auth_config: Dict[str, Any] = field(...)             # line 169
    token_supplier: Optional[Callable[[], Optional[str]]] = None  # line 171
    transport: str = "auto"                              # line 174

# From parrot/mcp/oauth.py:29
class TokenStore:
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

# From parrot/mcp/oauth.py:70
class VaultTokenStore(TokenStore):
    @staticmethod
    def _vault_name(user_id: str, server_name: str) -> str:  # line 88
        return f"mcp_oauth_{server_name}_{user_id}"

# From parrot/mcp/oauth.py:282
class OAuthManager:  # TO BE DEPRECATED
    def __init__(self, *, user_id, server_name, client_id, auth_url, token_url, scopes, ...)
    def token_supplier(self) -> Optional[str]:   # line 325
    async def ensure_token(self) -> str:          # line 335

# From parrot/mcp/integration.py:729
def create_oauth_mcp_server(*, name, url, user_id, client_id, auth_url,
    token_url, scopes, ...) -> MCPServerConfig:  # TO BE REFACTORED

# From parrot/auth/oauth2/registry.py:20
class OAuth2Provider(ABC):
    provider_id: str
    display_name: str
    default_scopes: ClassVar[List[str]] = []
    @property
    @abstractmethod
    def manager(self) -> Any: ...                # line 44
    @abstractmethod
    def toolkit_factory(self, credential_resolver) -> AbstractToolkit: ...  # line 53

# From parrot/auth/oauth2/registry.py:69
class OAuth2ProviderRegistry:  # singleton
    def register(self, provider: OAuth2Provider) -> None:  # line 96
    def get(self, provider_id: str) -> Optional[OAuth2Provider]:  # line 106
    def all(self) -> List[OAuth2Provider]:  # line 117

# From parrot/auth/oauth2/service.py:67
class IntegrationsService:
    async def list_for_user(self, user_id, agent_id, request=None): ...  # line 74
    async def start_connect(self, ...): ...
    async def persist_credential(self, ...): ...
    async def disconnect(self, ...): ...

# From parrot/mcp/registry.py:89
class UserMCPServerConfig(BaseModel):
    server_name: str        # line 108
    agent_id: str           # line 109
    user_id: str            # line 110
    params: Dict[str, Any]  # line 111 (non-secret)
    vault_credential_name: Optional[str]  # line 115
    active: bool = True     # line 119
```

#### MCP SDK OAuth2 (installed, v1.23.0)
```python
# From .venv/.../mcp/client/auth/oauth2.py:57
class PKCEParameters(BaseModel):
    code_verifier: str
    code_challenge: str
    @classmethod
    def generate(cls) -> "PKCEParameters": ...  # line 64

# From .venv/.../mcp/client/auth/oauth2.py:72
class TokenStorage(Protocol):
    async def get_tokens(self) -> OAuthToken | None: ...
    async def set_tokens(self, tokens: OAuthToken) -> None: ...
    async def get_client_info(self) -> OAuthClientInformationFull | None: ...
    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None: ...

# From .venv/.../mcp/client/auth/oauth2.py:92
@dataclass
class OAuthContext:
    server_url: str
    client_metadata: OAuthClientMetadata
    storage: TokenStorage
    redirect_handler: Callable[[str], Awaitable[None]] | None
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None
    timeout: float = 300.0

# From .venv/.../mcp/client/auth/extensions/client_credentials.py:24
class ClientCredentialsOAuthProvider:  # M2M auth
    # client_secret_basic or client_secret_post
```

#### Verified Imports
```python
from parrot.mcp.client import MCPClientConfig, AuthScheme, AuthCredential
from parrot.mcp.oauth import VaultTokenStore, TokenStore, OAuthManager, InMemoryTokenStore, RedisTokenStore
from parrot.mcp.integration import create_oauth_mcp_server, MCPClient, MCPEnabledMixin
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry, register_oauth2_provider
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet
from parrot.auth.oauth2_routes import setup_oauth2_routes
from parrot.mcp.registry import UserMCPServerConfig, MCPServerDescriptor
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential, delete_vault_credential

# MCP SDK (v1.23.0)
from mcp.client.auth.oauth2 import OAuthContext, TokenStorage, PKCEParameters
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.shared.auth import OAuthToken, OAuthClientMetadata, OAuthClientInformationFull, OAuthMetadata
```

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.mcp.oauth.MCPOAuth2Provider`~~ — does not exist yet (to be created)
- ~~`parrot.mcp.client.MCPOAuth2Config`~~ — does not exist yet (to be created)
- ~~`parrot.mcp.oauth.VaultMCPTokenStorage`~~ — does not exist yet (adapter to be created)
- ~~`MCPClientConfig.oauth2`~~ — field does not exist yet
- ~~`MCPClientConfig.auth_preset`~~ — field does not exist yet
- ~~`MCPServerDescriptor.auth_type`~~ — field does not exist yet
- ~~`parrot.auth.oauth2.mcp_provider`~~ — module does not exist yet
- ~~`OAuthManager` integration with `OAuth2ProviderRegistry`~~ — currently separate systems

---

## Parallelism Assessment

- **Internal parallelism**: Yes — tasks can be split:
  - `MCPOAuth2Config` model + preset registry (independent)
  - `VaultMCPTokenStorage` adapter (independent)
  - `MCPOAuth2Provider` + registry integration (depends on config model)
  - Transport integration in `HttpMCPSession` (depends on adapter)
  - Navigator callback route (independent)
  - Deprecation of `OAuthManager` + migration of factories (depends on all above)
- **Cross-feature independence**: Touches `parrot/mcp/` and `parrot/auth/oauth2/` — no
  known in-flight specs conflict. The MCP server registry is stable.
- **Recommended isolation**: per-spec
- **Rationale**: While some tasks are independent, they share `MCPClientConfig` and
  `parrot/mcp/oauth.py` heavily. A single worktree avoids merge conflicts between
  the adapter, config model, and transport integration changes.

---

## Open Questions

- [x] Should MCP OAuth2 presets be defined in code (like `MCPServerDescriptor`) or
      in a YAML file that users can extend? — *Owner: Jesus*: In code, like `MCPServerDescriptor`
- [x] Should we support RFC 7591 dynamic client registration (MCP SDK has it) or
      require `client_id` to be pre-configured? — *Owner: Jesus*: Yes, support it
- [x] Should the `OAuthManager` in `parrot/mcp/oauth.py` be fully removed or kept
      as deprecated for one release cycle? — *Owner: Jesus*: Fully remove
- [x] Should MCP OAuth2 tokens appear in the `IntegrationsService.list_for_user()`
      response alongside O365/Jira? — *Owner: Jesus*: Yes
