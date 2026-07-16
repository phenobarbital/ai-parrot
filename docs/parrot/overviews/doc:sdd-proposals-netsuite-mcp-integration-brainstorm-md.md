---
type: Wiki Overview
title: 'Brainstorm: NetSuite MCP Integration'
id: doc:sdd-proposals-netsuite-mcp-integration-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: NetSuite (Oracle) exposes an MCP server at `https://{ACCOUNT_ID}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools`
  that provides tools for record CRUD, reports, saved searches, and SuiteQL queries.
  It uses OAuth 2.0 Authorization Code Grant with P
relates_to:
- concept: mod:parrot.handlers.vault_utils
  rel: mentions
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.mcp.config
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.registry
  rel: mentions
- concept: mod:parrot.mcp.transports
  rel: mentions
- concept: mod:parrot.mcp.transports.http
  rel: mentions
---

# Brainstorm: NetSuite MCP Integration

**Date**: 2026-04-29
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

NetSuite (Oracle) exposes an MCP server at `https://{ACCOUNT_ID}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools` that provides tools for record CRUD, reports, saved searches, and SuiteQL queries. It uses OAuth 2.0 Authorization Code Grant with PKCE over Streamable HTTP transport (MCP protocol version `2025-06-18`).

Parrot agents need to connect to this MCP server so they can interact with NetSuite data (create/read/update records, run reports, execute queries) through the standard ToolManager pipeline. The integration should be generic enough to serve as a reference for any OAuth2-protected remote MCP server, with NetSuite as the first consumer.

**Who is affected:** Developers building agents that interact with NetSuite ERP data; end users querying NetSuite through Parrot-powered chatbots.

## Constraints & Requirements

- **OAuth2 Authorization Code + PKCE** is mandatory (NetSuite does not support client credentials for MCP scope)
- **Scope must be `mcp` alone** — cannot be combined with `restlets`, `rest_webservices`, or `suite_analytics`
- **Access tokens expire in 60 minutes**, refresh tokens in 2 days (public client, configurable up to 720h)
- **Administrator role cannot be used** — custom NetSuite role required with `MCP Server Connection` + `Log in using OAuth 2.0 Access Tokens` permissions
- **Token persistence**: Use Vault (encrypted DB) when a user session exists, in-memory otherwise
- **Transport**: Streamable HTTP (JSON-RPC over HTTP POST) — current `HttpMCPSession` protocol version `2024-11-05` may need update to `2025-06-18`
- **Single-account** for now (no multi-tenant)
- **All discovered tools exposed** to agents (no filtering)
- **Transparent token refresh** with fallback to error surfacing

---

## Options Explored

### Option A: Thin NetSuite Helper on Existing OAuth2 Infrastructure

Add a `create_netsuite_mcp_server()` factory function and `add_netsuite_mcp_server()` convenience method that constructs NetSuite-specific URLs from `account_id` and delegates entirely to the existing `create_oauth_mcp_server()` + `OAuthManager` pipeline. Add a `VaultTokenStore` implementation of the `TokenStore` interface for encrypted token persistence. Register NetSuite in the `MCPServerDescriptor` registry.

✅ **Pros:**
- Minimal new code (~150 lines): one factory function, one helper method, one `VaultTokenStore`, one registry entry
- Full reuse of battle-tested `OAuthManager` (PKCE, token refresh, interactive auth flow)
- Full reuse of `HttpMCPSession` transport and `MCPToolProxy` pipeline
- Consistent with existing patterns (`add_perplexity_mcp_server`, `add_fireflies_mcp_server`)
- Easy to test — most of the path is already covered by existing tests

❌ **Cons:**
- No protocol version negotiation (relies on `HttpMCPSession` hardcoded `2024-11-05`)
- No Streamable HTTP streaming response support (only request/response, no SSE fallback)
- URL template logic is NetSuite-specific, not generalized

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client for OAuth2 flows and MCP transport | Already in use |
| `navigator-session` | Vault encryption (AES-GCM) | Already in use, optional dependency |

🔗 **Existing Code to Reuse:**
- `parrot/mcp/integration.py:690` — `create_oauth_mcp_server()` factory (wire OAuth + MCPServerConfig)
- `parrot/mcp/oauth.py:605` — `OAuthManager` (Authorization Code + PKCE, token refresh)
- `parrot/mcp/oauth.py:560` — `TokenStore` interface + `InMemoryTokenStore` / `RedisTokenStore`
- `parrot/mcp/integration.py:1134` — `add_oauth_mcp_server()` convenience method pattern
- `parrot/mcp/registry.py:145` — `_REGISTRY` list for declarative server catalog
- `parrot/handlers/vault_utils.py:69` — `store_vault_credential()` / `retrieve_vault_credential()`
- `parrot/mcp/transports/http.py:178` — `HttpMCPSession` (JSON-RPC over HTTP POST)

---

### Option B: Generic OAuth2 Provider Template System

Introduce a `OAuthProviderTemplate` abstraction that maps `(provider_slug, account_id)` → `(mcp_url, auth_url, token_url, scopes, extra_params)`. NetSuite, Salesforce, and future providers register their URL templates. A `create_provider_mcp_server()` factory resolves the template and delegates to `OAuthManager`. Includes `VaultTokenStore` and protocol version negotiation.

✅ **Pros:**
- Future-proof for Salesforce, HubSpot, ServiceNow, etc.
- Clean separation between provider-specific URL construction and generic OAuth2 logic
- Protocol version can be per-provider

❌ **Cons:**
- Over-engineered for a single provider (YAGNI — we only have NetSuite now)
- Adds a new abstraction layer (`OAuthProviderTemplate`) that needs its own registry and validation
- Longer time to deliver for no immediate benefit

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client | Already in use |
| `navigator-session` | Vault encryption | Already in use |

🔗 **Existing Code to Reuse:**
- Same as Option A, plus new `OAuthProviderTemplate` abstraction

---

### Option C: Full NetSuite Toolkit with MCP Client Wrapper

Create a `NetSuiteToolkit(AbstractToolkit)` that internally manages its own MCP connection, OAuth2 lifecycle, and exposes NetSuite tools as native Parrot tools via the toolkit pattern. This bypasses the generic MCP pipeline and provides NetSuite-specific error handling, retry logic, and tool enrichment (e.g., adding NetSuite record type hints).

✅ **Pros:**
- Maximum control over NetSuite-specific behavior
- Can add NetSuite-specific features (record type caching, SuiteQL query builder)
- Independent lifecycle management

❌ **Cons:**
- Duplicates MCP client logic that already exists in `MCPClient` / `HttpMCPSession`
- Violates the design principle of using MCP for remote tool discovery
- High effort and maintenance burden
- Tools are not auto-discovered — must be manually mirrored from MCP

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client | Already in use |
| `navigator-session` | Vault encryption | Already in use |

🔗 **Existing Code to Reuse:**
- `parrot/tools/abstract.py` — `AbstractToolkit` base class
- `parrot/mcp/oauth.py:605` — `OAuthManager` (still reused for OAuth)

---

## Recommendation

**Option A** is recommended because:

1. **The infrastructure already exists.** The `OAuthManager` already implements Authorization Code + PKCE with token refresh — exactly what NetSuite requires. The `create_oauth_mcp_server()` factory already wires `OAuthManager` → `token_supplier` → `MCPServerConfig`. We're adding ~150 lines on top of a proven stack.

2. **YAGNI.** Option B's provider template system is premature abstraction. If a second OAuth2 provider needs MCP integration, we can extract the pattern then. The refactor from A→B is trivial — it's just pulling URL construction into a registry.

3. **Option C fights the architecture.** Parrot's MCP design is deliberately transport-agnostic with automatic tool discovery. A custom toolkit that duplicates this pipeline creates maintenance burden and misses the point of MCP.

The main tradeoff: Option A doesn't upgrade the MCP protocol version or add Streamable HTTP streaming. The current `HttpMCPSession` sends JSON-RPC POST requests and expects JSON responses — which is the non-streaming subset of Streamable HTTP and should work with NetSuite for tool listing and invocation. Protocol version upgrade can be a follow-up if NetSuite rejects `2024-11-05`.

---

## Feature Description

### User-Facing Behavior

A developer configures NetSuite MCP by providing their `account_id` and `client_id`:

```python
tools = await agent.add_netsuite_mcp_server(
    account_id="4984231",
    client_id="abc123-def456",
    user_id="user@company.com",
)
# First call triggers browser-based OAuth consent
# Agent now has tools: ns_createRecord, ns_getRecord, ns_runReport, etc.
```

In production with a user session (e.g., via chatbot integration), OAuth tokens are stored encrypted in the Vault and reused across sessions. In CLI/development mode, the user is prompted to authenticate via a browser URL, and tokens are stored in memory.

The agent's ToolManager exposes all NetSuite MCP tools (prefixed `mcp_netsuite_*`) alongside other tools. Agents use them transparently through the standard tool execution pipeline.

### Internal Behavior

1. **Configuration**: `add_netsuite_mcp_server(account_id, client_id, user_id)` constructs:
   - MCP URL: `https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools`
   - Auth URL: `https://{account_id}.app.netsuite.com/app/login/oauth2/authorize.nl`
   - Token URL: `https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token`
   - Scope: `["mcp"]`

2. **Token Store Selection**: If a Vault is available (user session context), creates `VaultTokenStore`; otherwise falls back to `InMemoryTokenStore`.

3. **OAuth Flow**: `OAuthManager` handles:
   - Loading cached token from store → if valid, use it
   - If expired + refresh token exists → attempt refresh
   - If refresh fails or no token → start interactive auth (local callback server + browser URL)

4. **Connection**: `MCPClient` connects via `HttpMCPSession`, discovers tools via `tools/list`, creates `MCPToolProxy` instances registered in `ToolManager`.

5. **Execution**: When agent calls a NetSuite tool:
   - `ToolManager.execute_tool()` → `MCPToolProxy._execute()` → `MCPClient.call_tool()`
   - `HttpMCPSession` sends JSON-RPC POST with Bearer token from `token_supplier`
   - If token expired, `token_supplier` returns `None` → caller triggers `ensure_token()` for refresh

### Edge Cases & Error Handling

- **Token expiry mid-session**: `OAuthManager.token_supplier()` detects tokens within 60s of expiry and returns `None`, triggering transparent refresh via `ensure_token()`. If refresh fails (e.g., refresh token expired after 2 days), surfaces an error to the agent.
- **First-time auth in headless environment**: Prints auth URL to stderr for the user to visit. Times out after 5 minutes if no callback received.
- **NetSuite role restrictions**: If the user's NetSuite role lacks `MCP Server Connection` permission, the MCP server will reject requests — surfaced as a tool execution error.
- **Network failures**: Existing `MCPSessionManager` retry logic handles transient errors with exponential backoff.
- **Invalid account_id**: NetSuite returns DNS resolution failure — caught as connection error.
- **Protocol version mismatch**: If NetSuite rejects `2024-11-05`, the error is surfaced. A follow-up task can upgrade to `2025-06-18`.

---

## Capabilities

### New Capabilities
- `netsuite-mcp-integration`: OAuth2-authenticated MCP client for NetSuite AI Connector Service
- `vault-token-store`: Encrypted token persistence via Vault for OAuth2 tokens

### Modified Capabilities
- `mcp-registry`: Add NetSuite to `MCPServerDescriptor` catalog (`_REGISTRY`)
- `mcp-integration`: Add `create_netsuite_mcp_server()` factory and `add_netsuite_mcp_server()` helper

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/mcp/integration.py` | extends | New factory `create_netsuite_mcp_server()` + helper `add_netsuite_mcp_server()` |
| `parrot/mcp/oauth.py` | extends | New `VaultTokenStore` class implementing `TokenStore` |
| `parrot/mcp/registry.py` | extends | New `MCPServerDescriptor` entry for NetSuite |
| `parrot/handlers/vault_utils.py` | depends on | Used by `VaultTokenStore` for encrypted storage |
| `parrot/mcp/transports/http.py` | no change | Existing `HttpMCPSession` used as-is (Streamable HTTP subset) |
| `parrot/mcp/client.py` | no change | `MCPClientConfig` already supports `token_supplier` |

---

## Code Context

### User-Provided Code
```python
# Source: user-provided (conversation)
# NetSuite MCP URL pattern:
# https://{NETSUITE_ACCOUNT_ID}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools
# Example with account 4984231:
# https://4984231.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools
```

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/mcp/oauth.py:605
class OAuthManager:
    def __init__(self, *, user_id: str, server_name: str, client_id: str,
                 auth_url: str, token_url: str, scopes: list[str],
                 redirect_host: str = "127.0.0.1", redirect_port: int = 8765,
                 redirect_path: str = "/mcp/oauth/callback",
                 token_store: TokenStore, client_secret: str | None = None,
                 extra_token_params: dict | None = None, http_timeout: float = 15.0): ...
    def token_supplier(self) -> Optional[str]: ...  # line 648
    async def ensure_token(self) -> str: ...  # line 658
    async def _refresh(self) -> bool: ...  # line 754

# From parrot/mcp/oauth.py:560
class TokenStore:
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

# From parrot/mcp/oauth.py:566
class InMemoryTokenStore(TokenStore): ...

# From parrot/mcp/oauth.py:580
class RedisTokenStore(TokenStore): ...

# From parrot/mcp/integration.py:690
def create_oauth_mcp_server(*, name: str, url: str, user_id: str, client_id: str,
                            auth_url: str, token_url: str, scopes: list[str],
                            client_secret: str | None = None, redis=None,
                            redirect_host: str = "127.0.0.1", redirect_port: int = 8765,
                            redirect_path: str = "/mcp/oauth/callback",
                            extra_token_params: dict | None = None,
                            headers: dict | None = None) -> MCPServerConfig: ...

# From parrot/mcp/integration.py:1134
async def add_oauth_mcp_server(self, name: str, url: str, client_id: str,
                               auth_url: str, token_url: str, scopes: List[str],
                               user_id: str, client_secret: Optional[str] = None,
                               **kwargs) -> List[str]: ...

# From parrot/mcp/integration.py:307
class MCPClient:
    def __init__(self, config: MCPServerConfig, tool_name_prefix: Optional[str] = None): ...
    async def connect(self): ...  # line 343
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None): ...  # line 388

# From parrot/mcp/transports/http.py:178
class HttpMCPSession:
    async def connect(self): ...  # line 190
    async def _send_request(self, method: str, params: dict = None) -> dict: ...  # line 238
    async def list_tools(self): ...  # line 304
    async def call_tool(self, tool_name: str, arguments: dict): ...  # line 319

# From parrot/mcp/registry.py:62
class MCPServerDescriptor(BaseModel):
    name: str  # Registry slug
    display_name: str
    description: str
    method_name: str  # MCPEnabledMixin method to call
    params: List[MCPServerParam]
    category: str = "general"
    activatable: bool = True

# From parrot/mcp/registry.py:44
class MCPServerParam(BaseModel):
    name: str
    type: MCPParamType  # STRING, INTEGER, BOOLEAN, SECRET
    required: bool = True
    default: Optional[Any] = None
    description: str = ""

# From parrot/mcp/config.py:16
@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    auth_type: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = None
    token_supplier: Optional[Callable[[], Optional[str]]] = None
    # ... many more fields
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.mcp.oauth import OAuthManager, TokenStore, InMemoryTokenStore, RedisTokenStore  # parrot/mcp/oauth.py
from parrot.mcp.integration import create_oauth_mcp_server, MCPClient  # parrot/mcp/integration.py
from parrot.mcp.config import MCPServerConfig  # parrot/mcp/config.py
from parrot.mcp.registry import MCPServerDescriptor, MCPServerParam, MCPParamType  # parrot/mcp/registry.py
from parrot.handlers.vault_utils import store_vault_credential, retrieve_vault_credential, delete_vault_credential  # parrot/handlers/vault_utils.py
from parrot.mcp.client import MCPClientConfig, AuthScheme, AuthCredential  # parrot/mcp/client.py
from parrot.mcp.transports.http import HttpMCPSession  # parrot/mcp/transports/http.py
```

#### Key Attributes & Constants
- `OAuthManager._verifier` → PKCE code verifier (parrot/mcp/oauth.py:643)
- `OAuthManager._challenge` → PKCE S256 challenge (parrot/mcp/oauth.py:644)
- `OAuthManager.redirect_uri` → Callback URI string (parrot/mcp/oauth.py:637)
- `MCPServerConfig.token_supplier` → `Callable[[], Optional[str]]` (parrot/mcp/config.py)
- `HttpMCPSession` protocol version → hardcoded `"2024-11-05"` (parrot/mcp/transports/http.py:228)
- `_REGISTRY` → `List[MCPServerDescriptor]` (parrot/mcp/registry.py:145)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.mcp.oauth.VaultTokenStore`~~ — does not exist yet (needs to be created)
- ~~`parrot.mcp.integration.create_netsuite_mcp_server`~~ — does not exist yet
- ~~`parrot.mcp.integration.MCPEnabledMixin.add_netsuite_mcp_server`~~ — does not exist yet
- ~~`parrot.mcp.netsuite`~~ — no NetSuite-specific module exists
- ~~`parrot.mcp.transports.streamable_http`~~ — no separate Streamable HTTP transport; HTTP transport uses plain JSON-RPC POST
- ~~`MCPServerConfig.protocol_version`~~ — not a configurable field; hardcoded in `HttpMCPSession._initialize_session()`

---

## NetSuite MCP Server Reference (from Oracle Documentation)

### Endpoints (account_id-parameterized)
| Endpoint | URL Template |
|---|---|
| MCP Server (standard tools) | `https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools` |
| MCP Server (all tools) | `https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/all` |
| OAuth2 Authorize | `https://{account_id}.app.netsuite.com/app/login/oauth2/authorize.nl` |
| OAuth2 Token | `https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token` |

### Tools Exposed by MCP Standard Tools SuiteApp
| Tool | Description | Permission |
|---|---|---|
| `ns_createRecord` | Creates a new record | REST Web Services (Full) |
| `ns_getRecord` | Retrieves a record | REST Web Services (Full) |
| `ns_getRecordTypeMetadata` | Record type metadata | REST Web Services (Full) |
| `ns_updateRecord` | Updates a record | REST Web Services (Full) |
| `ns_getSubsidiaries` | Lists subsidiaries | None |
| `ns_listAllReports` | Lists all reports | None |
| `ns_runReport` | Runs a report | None |
| `ns_listSavedSearches` | Lists saved searches | Perform Search (View) |
| `ns_runSavedSearch` | Runs a saved search | Perform Search (View) |
| `ns_runCustomSuiteQL` | Runs a SuiteQL query (read-only) | None |
| `ns_getSuiteQLMetadata` | SuiteQL metadata | None |

### OAuth2 Details
- **Flow**: Authorization Code Grant + PKCE (mandatory)
- **Scope**: `mcp` (must be used alone)
- **Access token TTL**: 60 minutes
- **Refresh token TTL**: 2 days (public client, configurable 1h–720h)
- **Required permissions**: `MCP Server Connection`, `Log in using OAuth 2.0 Access Tokens`
- **Restriction**: Administrator role cannot be used

---

## Parallelism Assessment

- **Internal parallelism**: Yes — `VaultTokenStore` (oauth.py), `create_netsuite_mcp_server` factory (integration.py), and registry entry (registry.py) touch different files and can be developed independently.
- **Cross-feature independence**: No conflicts with in-flight specs. Only extends existing modules; does not modify shared logic.
- **Recommended isolation**: `per-spec` — the feature is small enough (3-4 tasks) that a single worktree is efficient. The tasks have light dependencies (factory needs VaultTokenStore).
- **Rationale**: Low task count and sequential dependency chain (VaultTokenStore → factory → registry → tests) makes per-spec more efficient than spinning up multiple worktrees.

---

## Open Questions

- [ ] Should `HttpMCPSession` protocol version be upgraded from `2024-11-05` to `2025-06-18` as part of this feature, or as a separate follow-up? — *Owner: Jesus Lara*
- [ ] Does the `VaultTokenStore` need a TTL-based cleanup mechanism, or should tokens remain until explicitly deleted? — *Owner: Jesus Lara*
- [ ] Should we support the `/v1/all` URL variant (all SuiteApps) in addition to the standard tools URL, or just standard tools? — *Owner: Jesus Lara*
- [ ] What `client_id` should be used for the integration record? Does the user create one in NetSuite's UI, or is there a shared one? — *Owner: Jesus Lara*
- [ ] Should the `add_netsuite_mcp_server` helper live in `mcp_mixin.py` (alongside `add_github_mcp`) or in `integration.py` (alongside `add_perplexity_mcp_server`)? — *Owner: Jesus Lara*
