---
type: Wiki Overview
title: 'Feature Specification: NetSuite MCP Integration'
id: doc:sdd-specs-netsuite-mcp-integration-spec-md
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
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.registry
  rel: mentions
- concept: mod:parrot.mcp.transports
  rel: mentions
---

# Feature Specification: NetSuite MCP Integration

**Feature ID**: FEAT-135
**Date**: 2026-04-29
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

NetSuite (Oracle) exposes an MCP server at `https://{ACCOUNT_ID}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools` that provides tools for record CRUD, reports, saved searches, and SuiteQL queries. It uses OAuth 2.0 Authorization Code Grant with PKCE over Streamable HTTP transport (MCP protocol version `2025-06-18`).

Parrot agents need to connect to this MCP server so they can interact with NetSuite data (create/read/update records, run reports, execute queries) through the standard ToolManager pipeline. The integration should be generic enough to serve as a reference for any OAuth2-protected remote MCP server, with NetSuite as the first consumer.

**Who is affected:** Developers building agents that interact with NetSuite ERP data; end users querying NetSuite through Parrot-powered chatbots.

### Goals

- Enable Parrot agents to connect to the NetSuite MCP server using OAuth2 Authorization Code + PKCE
- Persist OAuth2 tokens securely using the Vault (encrypted DB) when a user session exists, with in-memory fallback
- Auto-discover and expose all NetSuite MCP tools through the standard ToolManager pipeline
- Follow existing MCP integration patterns (`add_perplexity_mcp_server`, `add_fireflies_mcp_server`)
- Register NetSuite in the `MCPServerDescriptor` catalog for activation via the MCP helper endpoint

### Non-Goals (explicitly out of scope)

- Protocol version upgrade from `2024-11-05` to `2025-06-18` — the current `HttpMCPSession` sends JSON-RPC POST requests (the non-streaming subset of Streamable HTTP) and should work as-is. Upgrade is a follow-up.
- Streamable HTTP streaming response support (SSE fallback) — only request/response is needed for tool listing and invocation.
- Multi-tenant / multi-account support — single-account configuration per agent.
- Tool filtering or enrichment — all discovered tools are exposed as-is.
- Generic OAuth2 provider template system — rejected in brainstorm as premature abstraction (Option B). If a second OAuth2 MCP provider appears, the refactor from this approach to a template system is trivial.
- Custom NetSuite toolkit bypassing MCP — rejected in brainstorm as duplicative of existing MCP pipeline (Option C). See `sdd/proposals/netsuite-mcp-integration.brainstorm.md` for full analysis.

---

## 2. Architectural Design

### Overview

**Option A: Thin NetSuite Helper on Existing OAuth2 Infrastructure** (recommended in brainstorm).

Add a `create_netsuite_mcp_server()` factory function and `add_netsuite_mcp_server()` convenience method that constructs NetSuite-specific URLs from `account_id` and delegates entirely to the existing `create_oauth_mcp_server()` + `OAuthManager` pipeline. Add a `VaultTokenStore` implementation of the `TokenStore` interface for encrypted token persistence. Register NetSuite in the `MCPServerDescriptor` registry.

This is ~150 lines of new code on top of a proven stack: `OAuthManager` already implements Authorization Code + PKCE with token refresh, `create_oauth_mcp_server()` already wires `OAuthManager` → `token_supplier` → `MCPClientConfig`, and `HttpMCPSession` handles JSON-RPC POST transport.

**User-facing API:**

```python
tools = await agent.add_netsuite_mcp_server(
    account_id="4984231",
    client_id="abc123-def456",
    user_id="user@company.com",
)
# First call triggers browser-based OAuth consent
# Agent now has tools: mcp_netsuite_ns_createRecord, mcp_netsuite_ns_getRecord, etc.
```

In production with a user session (e.g., via chatbot integration), OAuth tokens are stored encrypted in the Vault and reused across sessions. In CLI/development mode, the user is prompted to authenticate via a browser URL, and tokens are stored in memory.

### Component Diagram

```
Developer/Agent
       │
       ▼
MCPEnabledMixin.add_netsuite_mcp_server(account_id, client_id, user_id)
       │
       ├── create_netsuite_mcp_server()        ← NEW factory function
       │       │
       │       ├── Construct NetSuite URLs from account_id
       │       ├── Select token store: VaultTokenStore or InMemoryTokenStore
       │       └── Delegate to create_oauth_mcp_server()
       │                   │
       │                   ├── OAuthManager (PKCE, token refresh)
       │                   └── MCPClientConfig (token_supplier hook)
       │
       ▼
MCPClient.connect()
       │
       ├── HttpMCPSession (JSON-RPC POST with Bearer token)
       ├── tools/list → tool discovery
       └── MCPToolProxy instances → ToolManager
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MCPEnabledMixin` (integration.py:1087) | extends | New `add_netsuite_mcp_server()` convenience method |
| `create_oauth_mcp_server()` (integration.py:690) | delegates to | NetSuite factory constructs URLs then delegates |
| `OAuthManager` (oauth.py:605) | uses (unchanged) | Handles PKCE, token refresh, interactive auth |
| `TokenStore` (oauth.py:560) | extends | New `VaultTokenStore` implementation |
| `MCPClientConfig` (client.py:130) | uses (unchanged) | Aliased as `MCPServerConfig` in integration.py |
| `HttpMCPSession` (transports/http.py:178) | uses (unchanged) | JSON-RPC POST transport |
| `MCPClient` (integration.py:307) | uses (unchanged) | Connects, discovers tools, creates proxies |
| `_REGISTRY` (registry.py:145) | extends | New `MCPServerDescriptor` entry for NetSuite |
| `get_factory_map()` (registry.py:439) | extends | Add `"netsuite"` → `create_netsuite_mcp_server` mapping |
| `vault_utils` (handlers/vault_utils.py) | depends on | `VaultTokenStore` uses `store_vault_credential` / `retrieve_vault_credential` / `delete_vault_credential` |

### Data Models

No new Pydantic models required. The integration uses existing `MCPClientConfig` (dataclass) and `MCPServerDescriptor` / `MCPServerParam` (Pydantic models) as-is.

**NetSuite URL construction** (pure string formatting):

```python
NETSUITE_MCP_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools"
NETSUITE_AUTH_URL = "https://{account_id}.app.netsuite.com/app/login/oauth2/authorize.nl"
NETSUITE_TOKEN_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token"
NETSUITE_SCOPES = ["mcp"]
```

### New Public Interfaces

```python
# In packages/ai-parrot/src/parrot/mcp/integration.py

def create_netsuite_mcp_server(
    *,
    account_id: str,
    client_id: str,
    user_id: str,
    token_store: TokenStore | None = None,
    redirect_host: str = "127.0.0.1",
    redirect_port: int = 8765,
    redirect_path: str = "/mcp/oauth/callback",
    headers: dict | None = None,
) -> MCPServerConfig:
    """Create MCPClientConfig for NetSuite MCP server with OAuth2 PKCE."""
    ...


# In MCPEnabledMixin (packages/ai-parrot/src/parrot/mcp/integration.py)

async def add_netsuite_mcp_server(
    self,
    account_id: str,
    client_id: str,
    user_id: str,
    **kwargs,
) -> List[str]:
    """Add NetSuite MCP server capability to this agent."""
    ...


# In packages/ai-parrot/src/parrot/mcp/oauth.py

class VaultTokenStore(TokenStore):
    """Encrypted token persistence via Vault (AES-GCM)."""

    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]:
        ...

    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None:
        ...

    async def delete(self, user_id: str, server_name: str) -> None:
        ...
```

---

## 3. Module Breakdown

### Module 1: VaultTokenStore

- **Path**: `packages/ai-parrot/src/parrot/mcp/oauth.py`
- **Responsibility**: Implement `TokenStore` interface using Vault-encrypted persistence via `vault_utils`. Stores OAuth2 tokens (access_token, refresh_token, expires_at) encrypted in DocumentDB.
- **Depends on**: `vault_utils` (existing), `TokenStore` interface (existing)

### Module 2: NetSuite MCP Factory & Helper

- **Path**: `packages/ai-parrot/src/parrot/mcp/integration.py`
- **Responsibility**: `create_netsuite_mcp_server()` factory constructs NetSuite-specific URLs from `account_id`, selects `VaultTokenStore` or `InMemoryTokenStore`, and delegates to `create_oauth_mcp_server()`. `add_netsuite_mcp_server()` is the `MCPEnabledMixin` convenience method.
- **Depends on**: Module 1 (VaultTokenStore), `create_oauth_mcp_server()` (existing)

### Module 3: Registry Entry & Factory Map

- **Path**: `packages/ai-parrot/src/parrot/mcp/registry.py`
- **Responsibility**: Add `MCPServerDescriptor` for NetSuite to `_REGISTRY` with params `account_id`, `client_id`, `user_id`. Add `"netsuite"` entry to `get_factory_map()`.
- **Depends on**: Module 2 (factory function exists)

### Module 4: Unit & Integration Tests

- **Path**: `tests/mcp/test_netsuite_mcp.py`
- **Responsibility**: Unit tests for `VaultTokenStore`, `create_netsuite_mcp_server()`, URL construction, token store selection. Integration test validating the full config pipeline.
- **Depends on**: Modules 1, 2, 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_vault_token_store_get_set_delete` | Module 1 | Store, retrieve, and delete a token via VaultTokenStore (mocked vault_utils) |
| `test_vault_token_store_get_missing` | Module 1 | Returns `None` when credential does not exist in Vault |
| `test_vault_token_store_key_format` | Module 1 | Vault credential name follows `mcp_oauth_{server_name}_{user_id}` pattern |
| `test_netsuite_url_construction` | Module 2 | Verify MCP URL, auth URL, token URL are correctly templated from account_id |
| `test_netsuite_scopes` | Module 2 | Scope is `["mcp"]` only |
| `test_netsuite_factory_returns_config` | Module 2 | `create_netsuite_mcp_server()` returns valid `MCPClientConfig` with correct fields |
| `test_netsuite_factory_default_token_store` | Module 2 | Without explicit `token_store`, defaults to `InMemoryTokenStore` |
| `test_netsuite_factory_vault_token_store` | Module 2 | With explicit `VaultTokenStore`, uses it |
| `test_netsuite_registry_entry` | Module 3 | NetSuite appears in `_REGISTRY` with correct params |
| `test_netsuite_factory_map` | Module 3 | `get_factory_map()["netsuite"]` points to `create_netsuite_mcp_server` |

### Integration Tests

| Test | Description |
|---|---|
| `test_netsuite_config_pipeline` | Create config via factory, verify `token_supplier` is callable, verify `_ensure_oauth_token` is attached |

### Test Data / Fixtures

```python
@pytest.fixture
def netsuite_account_id():
    return "4984231"

@pytest.fixture
def netsuite_client_id():
    return "test-client-abc123"

@pytest.fixture
def netsuite_user_id():
    return "user@company.com"

@pytest.fixture
def sample_oauth_token():
    return {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_at": 9999999999,
        "token_type": "Bearer",
    }
```

---

## 5. Acceptance Criteria

- [ ] `VaultTokenStore` implements `TokenStore` interface (`get`, `set`, `delete`) using `vault_utils` for AES-GCM encrypted storage
- [ ] `create_netsuite_mcp_server()` constructs correct URLs for MCP, OAuth authorize, and OAuth token endpoints from `account_id`
- [ ] OAuth scope is `["mcp"]` (cannot be combined with other scopes)
- [ ] `add_netsuite_mcp_server()` is available on `MCPEnabledMixin` as a convenience method
- [ ] NetSuite is registered in `_REGISTRY` with `account_id` (STRING, required), `client_id` (SECRET, required), `user_id` (STRING, required) params
- [ ] `get_factory_map()` includes `"netsuite"` → `create_netsuite_mcp_server`
- [ ] Default `token_store` is `InMemoryTokenStore` when no explicit store is provided
- [ ] All unit tests pass: `pytest tests/mcp/test_netsuite_mcp.py -v`
- [ ] No breaking changes to existing `OAuthManager`, `create_oauth_mcp_server`, `MCPEnabledMixin`, or registry APIs
- [ ] Token refresh is transparent — handled by existing `OAuthManager._refresh()` mechanism

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

**NOTE:** The project uses a monorepo layout. Source files live under
`packages/ai-parrot/src/parrot/` — NOT `parrot/` directly.

### Verified Imports

```python
# These imports have been confirmed to work (2026-04-29):
from parrot.mcp.oauth import OAuthManager, TokenStore, InMemoryTokenStore, RedisTokenStore
    # verified: packages/ai-parrot/src/parrot/mcp/oauth.py:560-598

from parrot.mcp.integration import create_oauth_mcp_server, MCPClient
    # verified: packages/ai-parrot/src/parrot/mcp/integration.py:690, :307

from parrot.mcp.client import MCPClientConfig
    # verified: packages/ai-parrot/src/parrot/mcp/client.py:130

from parrot.mcp.registry import MCPServerDescriptor, MCPServerParam, MCPParamType
    # verified: packages/ai-parrot/src/parrot/mcp/registry.py:62, :44, :37

from parrot.handlers.vault_utils import store_vault_credential, retrieve_vault_credential, delete_vault_credential
    # verified: packages/ai-parrot/src/parrot/handlers/vault_utils.py:69, :116, :149
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/mcp/oauth.py
class TokenStore:                                    # line 560
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

class InMemoryTokenStore(TokenStore):                # line 566
    def __init__(self): ...
    _data: dict  # keyed by (user_id, server_name) tuples

class RedisTokenStore(TokenStore):                   # line 580
    def __init__(self, redis): ...
    @staticmethod
    def _key(user_id: str, server_name: str) -> str: ...  # returns "mcp:oauth:{server_name}:{user_id}"

class OAuthManager:                                  # line 605
    def __init__(self, *, user_id: str, server_name: str, client_id: str,
                 auth_url: str, token_url: str, scopes: list[str],
                 redirect_host: str = "127.0.0.1", redirect_port: int = 8765,
                 redirect_path: str = "/mcp/oauth/callback",
                 token_store: TokenStore, client_secret: str | None = None,
                 extra_token_params: dict | None = None, http_timeout: float = 15.0): ...
    def token_supplier(self) -> Optional[str]: ...   # line 648
    async def ensure_token(self) -> str: ...          # line 658

# packages/ai-parrot/src/parrot/mcp/integration.py
# NOTE: MCPServerConfig in this file is actually MCPClientConfig (aliased at line 17)

def create_oauth_mcp_server(                         # line 690
    *, name: str, url: str, user_id: str, client_id: str,
    auth_url: str, token_url: str, scopes: list[str],
    client_secret: str | None = None, redis=None,
    redirect_host: str = "127.0.0.1", redirect_port: int = 8765,
    redirect_path: str = "/mcp/oauth/callback",
    extra_token_params: dict | None = None,
    headers: dict | None = None,
) -> MCPServerConfig: ...
# Returns MCPClientConfig; also attaches cfg._ensure_oauth_token = oauth.ensure_token

class MCPClient:                                     # line 307
    def __init__(self, config: MCPServerConfig, tool_name_prefix: Optional[str] = None): ...
    async def connect(self): ...                      # line 343
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None): ...  # line 388

class MCPEnabledMixin:                               # line 1087
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]: ...  # line 1094
    async def add_oauth_mcp_server(self, name, url, client_id, auth_url, token_url,
                                    scopes, user_id, client_secret=None, **kwargs) -> List[str]: ...  # line 1134
    async def add_perplexity_mcp_server(self, api_key, name="perplexity", **kwargs) -> List[str]: ...  # line 1161
    async def add_fireflies_mcp_server(self, api_key, **kwargs) -> List[str]: ...  # line 1171

# packages/ai-parrot/src/parrot/mcp/client.py
@dataclass
class MCPClientConfig:                               # line 130
    name: str
    url: Optional[str] = None
    auth_type: Optional[AuthScheme] = None
    auth_config: Dict[str, Any] = field(default_factory=dict)
    token_supplier: Optional[Callable[[], Optional[str]]] = None  # line 170
    transport: str = "auto"
    headers: Dict[str, str] = field(default_factory=dict)

# packages/ai-parrot/src/parrot/mcp/transports/http.py
class HttpMCPSession:                                # line 178
    def __init__(self, config: MCPClientConfig, logger): ...
    async def connect(self): ...                      # line 190
    async def _initialize_session(self): ...          # line 223
    # protocolVersion hardcoded as "2024-11-05" at line 227

# packages/ai-parrot/src/parrot/mcp/registry.py
class MCPServerDescriptor(BaseModel):                # line 62
    name: str; display_name: str; description: str; method_name: str
    params: List[MCPServerParam]; category: str = "general"; activatable: bool = True

class MCPServerParam(BaseModel):                     # line 44
    name: str; type: MCPParamType; required: bool = True
    default: Optional[Any] = None; description: str = ""

_REGISTRY: List[MCPServerDescriptor] = [...]         # line 145

def get_factory_map() -> Dict[str, Any]: ...         # line 439
# Currently maps: perplexity, fireflies, chrome-devtools, google-maps, alphavantage, quic, websocket

# packages/ai-parrot/src/parrot/handlers/vault_utils.py
async def store_vault_credential(user_id: str, vault_name: str,
                                  secret_params: Dict[str, Any]) -> None: ...  # line 69
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]: ...  # line 116
# Raises KeyError if not found
async def delete_vault_credential(user_id: str, vault_name: str) -> None: ...  # line 149
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VaultTokenStore.get()` | `retrieve_vault_credential()` | function call | `handlers/vault_utils.py:116` |
| `VaultTokenStore.set()` | `store_vault_credential()` | function call | `handlers/vault_utils.py:69` |
| `VaultTokenStore.delete()` | `delete_vault_credential()` | function call | `handlers/vault_utils.py:149` |
| `create_netsuite_mcp_server()` | `create_oauth_mcp_server()` | delegation | `mcp/integration.py:690` |
| `add_netsuite_mcp_server()` | `MCPEnabledMixin.add_mcp_server()` | method call | `mcp/integration.py:1094` |
| NetSuite `MCPServerDescriptor` | `_REGISTRY` list | append | `mcp/registry.py:145` |
| `"netsuite"` factory entry | `get_factory_map()` | dict entry | `mcp/registry.py:439` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.mcp.oauth.VaultTokenStore`~~ — does not exist yet (needs to be created)
- ~~`parrot.mcp.integration.create_netsuite_mcp_server`~~ — does not exist yet
- ~~`parrot.mcp.integration.MCPEnabledMixin.add_netsuite_mcp_server`~~ — does not exist yet
- ~~`parrot.mcp.netsuite`~~ — no NetSuite-specific module exists; all code goes in existing files
- ~~`parrot.mcp.transports.streamable_http`~~ — no separate Streamable HTTP transport; `HttpMCPSession` uses plain JSON-RPC POST
- ~~`MCPClientConfig.protocol_version`~~ — not a configurable field; hardcoded `"2024-11-05"` in `HttpMCPSession._initialize_session()` at line 227
- ~~`MCPServerConfig` (standalone class)~~ — does NOT exist in `integration.py`; `MCPServerConfig` is an alias for `MCPClientConfig` (imported at line 17)
- ~~`parrot/mcp/oauth.py`~~ — WRONG path; correct path is `packages/ai-parrot/src/parrot/mcp/oauth.py`
- ~~`parrot/mcp/integration.py`~~ — WRONG path; correct path is `packages/ai-parrot/src/parrot/mcp/integration.py`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Factory + helper pattern**: Follow `create_perplexity_mcp_server()` + `add_perplexity_mcp_server()` pattern exactly (see integration.py:1161-1169)
- **TokenStore subclass pattern**: Follow `RedisTokenStore` (oauth.py:580-598) — same `_key()` naming scheme adapted for Vault credential names
- **Registry entry pattern**: Follow existing `MCPServerDescriptor` entries in `_REGISTRY` (registry.py:145+)
- **Vault key naming**: Use `mcp_oauth_{server_name}_{user_id}` pattern, consistent with `mcp_perplexity_agent-1` convention seen in vault_utils.py:18
- **Import alias**: In integration.py, `MCPServerConfig` is `MCPClientConfig` — use the alias when adding code to integration.py, use `MCPClientConfig` directly elsewhere

### Known Risks / Gotchas

- **Protocol version mismatch**: NetSuite's MCP server uses protocol `2025-06-18` but `HttpMCPSession` sends `2024-11-05`. If NetSuite rejects the version, the error is surfaced as a connection failure. This is a known limitation — protocol upgrade is a follow-up task.
- **Token expiry mid-session**: `OAuthManager.token_supplier()` returns `None` when tokens are within 60s of expiry (oauth.py:654), triggering refresh. If refresh fails (refresh token expired after 2 days), an error is surfaced to the agent.
- **First-time auth in headless environment**: OAuthManager prints auth URL to stderr for the user to visit. Times out after 5 minutes if no callback received.
- **Vault dependency**: `VaultTokenStore` requires `navigator-session` for AES-GCM encryption. If unavailable, it should fall back gracefully (raise clear error at construction time, not at runtime).
- **Administrator role restriction**: NetSuite does not allow the Administrator role for MCP connections — requires a custom role with `MCP Server Connection` + `Log in using OAuth 2.0 Access Tokens` permissions. This is a NetSuite configuration requirement, not a code issue.
- **Scope restriction**: The `mcp` scope cannot be combined with `restlets`, `rest_webservices`, or `suite_analytics`. The factory hardcodes `["mcp"]`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | (already in use) | HTTP client for OAuth2 flows and MCP transport |
| `navigator-session` | (already in use, optional) | Vault encryption (AES-GCM) for `VaultTokenStore` |

---

## 8. Open Questions

- [x] Should `HttpMCPSession` protocol version be upgraded from `2024-11-05` to `2025-06-18` as part of this feature, or as a separate follow-up? — *Owner: Jesus Lara*: be upgraded
- [x] Does the `VaultTokenStore` need a TTL-based cleanup mechanism, or should tokens remain until explicitly deleted? — *Owner: Jesus Lara*: remains without ttl.
- [x] Should we support the `/v1/all` URL variant (all SuiteApps) in addition to the standard tools URL, or just standard tools? — *Owner: Jesus Lara*: just standard tools
- [ ] What `client_id` should be used for the integration record? Does the user create one in NetSuite's UI, or is there a shared one? — *Owner: Jesus Lara*: add documentation how to generate or obtain the client_id
- [ ] Should the `add_netsuite_mcp_server` helper live in `MCPEnabledMixin` (integration.py, alongside `add_perplexity_mcp_server`) or elsewhere? — *Owner: Jesus Lara*: in `MCPEnabledMixin`

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — sequential tasks in a single worktree
- **Rationale**: Small feature (4 tasks) with a sequential dependency chain (VaultTokenStore → factory → registry → tests). Spinning up multiple worktrees adds overhead with no benefit.
- **Cross-feature dependencies**: None. Only extends existing modules; does not modify shared logic.

---

…(truncated)…
