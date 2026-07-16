---
type: Wiki Overview
title: 'Feature Specification: MCP Server OAuth2 Support'
id: doc:sdd-specs-mcp-server-oauth2-support-spec-md
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
- concept: mod:parrot.mcp.oauth2_config
  rel: mentions
- concept: mod:parrot.mcp.oauth2_storage
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

# Feature Specification: MCP Server OAuth2 Support

**Feature ID**: FEAT-262
**Date**: 2026-06-26
**Author**: Jesus / Claude
**Status**: approved
**Target version**: 0.26.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot can consume external MCP servers, but authentication support is fragmented
across two independent OAuth2 systems:

1. **`parrot.mcp.oauth.OAuthManager`** — MCP-specific, spins up a local HTTP callback
   server on `localhost:8765`, uses its own `TokenStore` hierarchy
   (`InMemoryTokenStore`, `RedisTokenStore`, `VaultTokenStore`).
2. **`parrot.auth.oauth2_base.AbstractOAuth2Manager`** — general-purpose, uses the
   Navigator app server for callbacks, has provider registry + PBAC + distributed
   lock-protected refresh, with concrete providers for O365 and Jira.

When a user wants to connect to an OAuth2-protected MCP server (e.g., Fireflies.ai,
NetSuite, GitHub MCP, Google MCP), they must either use `create_oauth_mcp_server()`
which spins up a standalone local callback server (conflicts when Navigator is
running), or manually wire `AbstractOAuth2Manager` with no MCP integration path.

Meanwhile, the MCP Python SDK v1.23.0 ships its own full OAuth2 implementation
(`mcp.client.auth.oauth2.OAuthClientProvider`) with PKCE, RFC 8414 metadata discovery,
RFC 7591 dynamic client registration, and RFC 8707 resource indicators — none of which
AI-Parrot currently leverages.

### Goals

- Unify MCP OAuth2 under `parrot.auth.oauth2` — eliminate the parallel system.
- Use the MCP SDK's native OAuth2 for protocol-level flow mechanics (PKCE, discovery,
  dynamic registration, resource indicators).
- Use navigator-auth's vault for encrypted token persistence (per-user + per-server).
- Support both interactive (browser-based) and headless (client_credentials) auth flows.
- Support auto-re-auth on token expiry (transparent token refresh and retry).
- Provide zero-config presets for known OAuth2 MCP servers (Fireflies, NetSuite, etc.).
- Support inline OAuth2 configuration for custom/unknown MCP servers via YAML or code.
- Extend `MCPClientConfig` with `oauth2` and `auth_preset` fields.
- Route browser-based OAuth2 callbacks through the Navigator app server.

### Non-Goals (explicitly out of scope)

- Rewriting the existing O365/Jira OAuth2 providers to use MCP SDK internals — those
  are stable and operate outside MCP. This feature targets MCP server consumption only.
- Server-side OAuth2 (i.e., AI-Parrot acting as an OAuth2 provider for its own MCP
  servers) — `MCPServerConfig.auth_method` already handles that.
- Runtime fallback-on-failure was rejected in brainstorm — see
  `proposals/mcp-server-oauth2-support.brainstorm.md` Option B.
- Custom OAuth2 reimplementation was rejected in brainstorm — see Option C.

---

## 2. Architectural Design

### Overview

The recommended approach (brainstorm Option A: Unified OAuth2 Provider Bridge) creates
a thin adapter layer where:

- The **MCP SDK** (`mcp.client.auth.oauth2`) handles protocol-level OAuth2: PKCE
  generation, RFC 8414 authorization server metadata discovery, RFC 7591 dynamic client
  registration, RFC 8707 resource indicators, and token refresh.
- **AI-Parrot** (`parrot.auth.oauth2`) handles orchestration: provider registry,
  vault-backed token persistence, PBAC policy evaluation, Navigator callback routing,
  and the unified `IntegrationsService` dashboard.

Key adapter: `VaultMCPTokenStorage` implements the MCP SDK's `TokenStorage` protocol
by delegating to AI-Parrot's existing `VaultTokenStore` for token get/set and to
DocumentDB for client info get/set.

Configuration flows through `MCPClientConfig`, which gains an `oauth2` field
(`MCPOAuth2Config` Pydantic model) and an `auth_preset` field. When either is set,
the transport layer (`HttpMCPSession`) injects the MCP SDK's `OAuthClientProvider`
or `ClientCredentialsOAuthProvider` as the httpx auth handler.

Presets provide zero-config defaults for known servers: setting `auth_preset: netsuite`
auto-fills `auth_url`, `token_url`, `scopes`, and `grant_type` from the presets
registry. Users can override any field via the `oauth2:` block.

### Component Diagram

```
                                  ┌─────────────────────┐
                                  │  MCPClientConfig     │
                                  │  + oauth2: Config    │
                                  │  + auth_preset: str  │
                                  └──────┬──────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │   HttpMCPSession     │
                              │   (transport layer)  │
                              └──────────┬──────────┘
                                         │ injects
                    ┌────────────────────▼────────────────────┐
                    │        MCP SDK OAuthClientProvider       │
                    │  (PKCE, discovery, registration, refresh)│
                    └────────────────────┬────────────────────┘
                                         │ delegates to
                    ┌────────────────────▼────────────────────┐
                    │      VaultMCPTokenStorage (adapter)      │
                    │  implements mcp.client.auth.TokenStorage  │
                    └──────┬─────────────────────┬────────────┘
                           │                     │
              ┌────────────▼────────┐  ┌────────▼──────────┐
              │  VaultTokenStore    │  │  DocumentDB        │
              │  (token get/set)    │  │  (client_info)     │
              └─────────────────────┘  └────────────────────┘
                           │
              ┌────────────▼────────────────────┐
              │  OAuth2ProviderRegistry          │
              │  + MCPOAuth2Provider per server  │
              └─────────────────────────────────┘
                           │
              ┌────────────▼────────────────────┐
              │  IntegrationsService             │
              │  (list, connect, disconnect)     │
              └─────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MCPClientConfig` (`parrot/mcp/client.py:131`) | extends | Add `oauth2: MCPOAuth2Config` and `auth_preset: str` fields |
| `MCPClientConfig.from_yaml_config()` (`client.py:277`) | modifies | Parse `oauth2:` and `auth_preset:` keys from YAML |
| `MCPClientConfig.get_headers()` (`client.py:224`) | modifies | Delegate to OAuth2 provider when `oauth2` is set |
| `HttpMCPSession` (`ai-parrot-server, transports/http.py:185`) | modifies | Inject MCP SDK OAuth2 auth handler |
| `MCPClient.connect()` (`integration.py:311`) | modifies | Pass OAuth2 config to transport session |
| `MCPEnabledMixin.add_oauth_mcp_server()` (`integration.py:1358`) | modifies | Refactor to use unified OAuth2 |
| `create_oauth_mcp_server()` (`integration.py:729`) | modifies | Refactor internals, deprecate `OAuthManager` usage |
| `create_netsuite_mcp_server()` (`integration.py:802`) | modifies | Use preset + unified config |
| `OAuth2ProviderRegistry` (`auth/oauth2/registry.py:69`) | extends | Register `MCPOAuth2Provider` per server |
| `IntegrationsService` (`auth/oauth2/service.py:67`) | extends | Surface MCP OAuth2 tokens |
| `setup_oauth2_routes()` (`auth/oauth2_routes.py:199`) | extends | Add MCP callback route |
| `MCPServerDescriptor` (`mcp/registry.py:62`) | extends | Add `auth_type` field |
| `VaultTokenStore` (`mcp/oauth.py:70`) | reuses | Underlying storage for `VaultMCPTokenStorage` |
| MCP SDK `TokenStorage` (`.venv/.../mcp/client/auth/oauth2.py:72`) | implements | `VaultMCPTokenStorage` adapter |
| MCP SDK `OAuthClientProvider` | depends on | Flow mechanics |
| MCP SDK `ClientCredentialsOAuthProvider` | depends on | M2M headless flows |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class MCPOAuth2GrantType(str, Enum):
    AUTHORIZATION_CODE = "authorization_code"
    CLIENT_CREDENTIALS = "client_credentials"


class MCPOAuth2Config(BaseModel):
    """OAuth2 configuration for an MCP server connection.

    Can be fully specified inline or partially filled via a preset
    (auth_preset on MCPClientConfig) with per-field overrides.

    When client_id is omitted, RFC 7591 dynamic client registration
    is attempted via the MCP SDK's OAuthContext.
    """
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    auth_url: Optional[str] = None
    token_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    grant_type: MCPOAuth2GrantType = MCPOAuth2GrantType.AUTHORIZATION_CODE
    redirect_path: str = "/api/auth/oauth2/mcp/callback"
    extra_token_params: Optional[dict] = None


class MCPOAuth2Preset(BaseModel):
    """Built-in preset for a known OAuth2-protected MCP server."""
    name: str
    display_name: str
    auth_url: str
    token_url: str
    scopes: List[str]
    grant_type: MCPOAuth2GrantType = MCPOAuth2GrantType.AUTHORIZATION_CODE
    url_template: Optional[str] = None
    required_params: List[str] = Field(default_factory=list)
```

### New Public Interfaces

```python
class VaultMCPTokenStorage:
    """Adapter: MCP SDK TokenStorage protocol → AI-Parrot VaultTokenStore.

    Bridges the MCP SDK's token storage interface with AI-Parrot's
    encrypted vault persistence layer.
    """
    def __init__(self, user_id: str, server_name: str,
                 vault_store: VaultTokenStore | None = None): ...
    async def get_tokens(self) -> OAuthToken | None: ...
    async def set_tokens(self, tokens: OAuthToken) -> None: ...
    async def get_client_info(self) -> OAuthClientInformationFull | None: ...
    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None: ...


class MCPOAuth2Provider(OAuth2Provider):
    """OAuth2Provider implementation for MCP servers.

    Registered in OAuth2ProviderRegistry so MCP OAuth2 tokens appear
    in IntegrationsService alongside O365/Jira.
    """
    provider_id: str  # "mcp:{server_name}"
    display_name: str
    default_scopes: List[str]

    @property
    def manager(self) -> Any: ...
    def toolkit_factory(self, credential_resolver) -> AbstractToolkit: ...


def get_mcp_oauth2_preset(name: str) -> MCPOAuth2Preset | None:
    """Look up a built-in OAuth2 preset by name."""

def list_mcp_oauth2_presets() -> list[MCPOAuth2Preset]:
    """List all available OAuth2 presets."""
```

---

## 3. Module Breakdown

### Module 1: MCPOAuth2Config Model & Presets Registry

- **Path**: `parrot/mcp/oauth2_config.py` (new file)
- **Responsibility**: Define `MCPOAuth2Config`, `MCPOAuth2Preset`, `MCPOAuth2GrantType`
  Pydantic models and the presets registry. Presets are defined **in code** following
  the same pattern as `MCPServerDescriptor` (a module-level `_PRESETS` list of
  `MCPOAuth2Preset` instances, with lookup functions). Support RFC 7591 dynamic client
  registration: when `client_id` is not provided, the flow auto-registers via the
  MCP SDK's `OAuthContext` dynamic registration support.
- **Depends on**: None (standalone models)

### Module 2: VaultMCPTokenStorage Adapter

- **Path**: `parrot/mcp/oauth2_storage.py` (new file)
- **Responsibility**: Implement the MCP SDK's `TokenStorage` protocol, delegating
  `get_tokens`/`set_tokens` to `VaultTokenStore` (with `OAuthToken` ↔ `dict`
  conversion) and `get_client_info`/`set_client_info` to DocumentDB via vault_utils.
- **Depends on**: Module 1 (for `MCPOAuth2Config`), existing `VaultTokenStore`

### Module 3: MCPOAuth2Provider & Registry Integration

- **Path**: `parrot/auth/oauth2/mcp_provider.py` (new file)
- **Responsibility**: `MCPOAuth2Provider` subclass of `OAuth2Provider` that wraps an
  MCP OAuth2 config and exposes it through the unified `OAuth2ProviderRegistry`.
  Includes a factory function `register_mcp_oauth2_provider(server_name, config)`.
- **Depends on**: Module 1, Module 2, existing `OAuth2ProviderRegistry`

### Module 4: MCPClientConfig Extension

- **Path**: `parrot/mcp/client.py` (modify existing)
- **Responsibility**: Add `oauth2: Optional[MCPOAuth2Config]` and
  `auth_preset: Optional[str]` fields to `MCPClientConfig`. Update
  `from_yaml_config()` to parse these fields (resolve preset → merge overrides →
  construct `MCPOAuth2Config`). Update `get_headers()` to skip static auth when
  `oauth2` is set (transport handles auth).
- **Depends on**: Module 1

### Module 5: Transport OAuth2 Integration

- **Path**: `parrot/mcp/transports/http.py` (modify in ai-parrot-server),
  `parrot/mcp/integration.py` (modify in ai-parrot)
- **Responsibility**: In `HttpMCPSession.connect()`, detect `config.oauth2` and
  inject the MCP SDK's `OAuthClientProvider` (or `ClientCredentialsOAuthProvider`
  for `grant_type=client_credentials`) with a `VaultMCPTokenStorage` instance.
  Wire `redirect_handler` to open a browser and `callback_handler` to await the
  Navigator callback. Refactor `create_oauth_mcp_server()` and
  `create_netsuite_mcp_server()` to use the new config model.
- **Depends on**: Module 1, Module 2, Module 4

### Module 6: Navigator Callback Route

- **Path**: `parrot/auth/oauth2_routes.py` (modify existing)
- **Responsibility**: Add an MCP-specific OAuth2 callback handler at
  `/api/auth/oauth2/mcp/callback` that receives the authorization code,
  dispatches it to the correct `OAuthContext` by `state` parameter, and
  renders the "Authentication complete" response.
- **Depends on**: Module 2, Module 5

### Module 7: OAuthManager Removal & Factory Migration

- **Path**: `parrot/mcp/oauth.py` (modify), `parrot/mcp/integration.py` (modify)
- **Responsibility**: **Fully remove** `OAuthManager` class from `parrot/mcp/oauth.py`
  (no deprecation cycle). Keep `TokenStore`, `InMemoryTokenStore`, `RedisTokenStore`,
  `VaultTokenStore`, and `NetSuiteM2MAuth` — only the `OAuthManager` class is deleted.
  Update `MCPEnabledMixin.add_oauth_mcp_server()`, `add_fireflies_mcp_server()`,
  and other factory methods to use the new `MCPOAuth2Config`-based approach.
  Update `MCPServerDescriptor` with `auth_type` field.
- **Depends on**: All above modules

### Module 8: Tests

- **Path**: `tests/mcp/test_oauth2_config.py`, `tests/mcp/test_oauth2_storage.py`,
  `tests/mcp/test_oauth2_integration.py`, `tests/auth/test_mcp_oauth2_provider.py`
- **Responsibility**: Unit tests for config models, storage adapter, provider
  registration, and integration tests for the end-to-end OAuth2 flow with mocked
  OAuth2 server.
- **Depends on**: All above modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_mcp_oauth2_config_defaults` | Module 1 | Default values for `MCPOAuth2Config` |
| `test_mcp_oauth2_config_validation` | Module 1 | `client_id` is required, `grant_type` enum validation |
| `test_preset_lookup` | Module 1 | `get_mcp_oauth2_preset("netsuite")` returns correct config |
| `test_preset_not_found` | Module 1 | Unknown preset returns `None` |
| `test_vault_storage_get_tokens` | Module 2 | Retrieve tokens via `VaultTokenStore`, convert to `OAuthToken` |
| `test_vault_storage_set_tokens` | Module 2 | Store `OAuthToken` via `VaultTokenStore` |
| `test_vault_storage_no_token` | Module 2 | Returns `None` when vault has no entry |
| `test_vault_storage_graceful_degradation` | Module 2 | Vault unavailable → returns `None`, logs warning |
| `test_mcp_provider_registration` | Module 3 | `MCPOAuth2Provider` registers in `OAuth2ProviderRegistry` |
| `test_mcp_provider_listed` | Module 3 | MCP providers appear in `registry.all()` |
| `test_config_with_oauth2_field` | Module 4 | `MCPClientConfig` accepts `oauth2` as `MCPOAuth2Config` |
| `test_config_with_preset` | Module 4 | `from_yaml_config` resolves `auth_preset` → fills `oauth2` |
| `test_config_preset_with_overrides` | Module 4 | Preset defaults merged with inline `oauth2:` overrides |
| `test_oauth_manager_removed` | Module 7 | `OAuthManager` no longer importable from `parrot.mcp.oauth` |

### Integration Tests

| Test | Description |
|---|---|
| `test_oauth2_code_flow_mock` | Full authorization code + PKCE flow against a mock OAuth2 server |
| `test_client_credentials_flow_mock` | Client credentials grant against a mock token endpoint |
| `test_token_refresh_on_expiry` | Token expires → auto-refresh → tool call succeeds |
| `test_vault_round_trip` | Store token in vault → restart → retrieve token → tool call succeeds |
| `test_yaml_config_oauth2_server` | Load YAML with `oauth2:` block → `MCPClientConfig` has correct OAuth2 config |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_oauth2_server():
    """aiohttp test server that acts as an OAuth2 authorization + token endpoint."""
    ...

@pytest.fixture
def mcp_oauth2_config():
    return MCPOAuth2Config(
        client_id="test-client",
        auth_url="http://localhost:9999/authorize",
        token_url="http://localhost:9999/token",
        scopes=["read", "write"],
    )

@pytest.fixture
def vault_token_storage(mcp_oauth2_config):
    """VaultMCPTokenStorage with in-memory VaultTokenStore backend."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `MCPClientConfig` accepts `oauth2: MCPOAuth2Config` and `auth_preset: str` fields
- [ ] `MCPClientConfig.from_yaml_config()` parses `oauth2:` and `auth_preset:` keys
- [ ] `VaultMCPTokenStorage` implements MCP SDK's `TokenStorage` protocol
- [ ] `VaultMCPTokenStorage` delegates to `VaultTokenStore` for encrypted persistence
- [ ] `VaultMCPTokenStorage` gracefully degrades when vault is unavailable
- [ ] Token scoping is per-user + per-server (`mcp_oauth_{server}_{user_id}`)
- [ ] Authorization code flow with PKCE works end-to-end (mock server)
- [ ] Client credentials flow works end-to-end (mock server)
- [ ] Expired tokens are automatically refreshed before tool calls
- [ ] `MCPOAuth2Provider` registered in `OAuth2ProviderRegistry` for each configured server
- [ ] MCP OAuth2 tokens visible via `IntegrationsService.list_for_user()`
- [ ] Navigator callback route at `/api/auth/oauth2/mcp/callback` handles MCP callbacks
- [ ] At least one built-in preset exists (NetSuite)
- [ ] `OAuthManager` class fully removed from `parrot/mcp/oauth.py`
- [ ] `TokenStore`, `VaultTokenStore`, `InMemoryTokenStore`, `RedisTokenStore` kept intact
- [ ] RFC 7591 dynamic client registration works when `client_id` is omitted
- [ ] MCP OAuth2 presets defined in code (same pattern as `MCPServerDescriptor`)
- [ ] MCP OAuth2 tokens visible in `IntegrationsService.list_for_user()`
- [ ] Existing `add_fireflies_mcp_server()` and `add_perplexity_mcp_server()` keep working
- [ ] All unit tests pass: `pytest tests/mcp/test_oauth2_*.py tests/auth/test_mcp_oauth2_provider.py -v`
- [ ] All integration tests pass: `pytest tests/mcp/test_oauth2_integration.py -v`
- [ ] No breaking changes to existing `MCPClientConfig` or `MCPEnabledMixin` APIs
- [ ] Constraint: async-first — no blocking I/O in async contexts
- [ ] Constraint: all OAuth2 config uses Pydantic models with validation
- [ ] Constraint: navigator-auth vault used for token persistence (not custom store)

---

## 6. Codebase Contract

### Verified Imports

```python
# Core MCP client config (verified: parrot/mcp/client.py)
from parrot.mcp.client import MCPClientConfig, AuthScheme, AuthCredential  # line 131, 15, 26

# MCP OAuth token stores (verified: parrot/mcp/oauth.py)
from parrot.mcp.oauth import VaultTokenStore, TokenStore, OAuthManager  # line 70, 29, 282
from parrot.mcp.oauth import InMemoryTokenStore, RedisTokenStore  # line 35, 49

# MCP integration (verified: parrot/mcp/integration.py)
from parrot.mcp.integration import create_oauth_mcp_server, MCPClient  # line 729, 311
from parrot.mcp.integration import MCPEnabledMixin  # line 1311

# OAuth2 provider registry (verified: parrot/auth/oauth2/registry.py)
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry  # line 20, 69
from parrot.auth.oauth2.registry import register_oauth2_provider  # line 126

# OAuth2 service (verified: parrot/auth/oauth2/service.py)
from parrot.auth.oauth2.service import IntegrationsService  # line 67

# OAuth2 routes (verified: parrot/auth/oauth2_routes.py)
from parrot.auth.oauth2_routes import setup_oauth2_routes  # line 199

# MCP server registry (verified: parrot/mcp/registry.py)
from parrot.mcp.registry import UserMCPServerConfig, MCPServerDescriptor  # line 89, 62

# Vault utilities (verified: parrot/security/vault_utils.py)
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential  # used in oauth.py:14

# MCP SDK v1.23.0 (verified: .venv/.../mcp/client/auth/oauth2.py)
from mcp.client.auth.oauth2 import OAuthContext, PKCEParameters  # line 92, 57
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider  # line 24
from mcp.shared.auth import OAuthToken, OAuthClientMetadata, OAuthClientInformationFull  # verified
```

### Existing Class Signatures

```python
# parrot/mcp/client.py:131
@dataclass
class MCPClientConfig:
    name: str                                                          # line 155
    url: Optional[str] = None                                          # line 158
    command: Optional[str] = None                                      # line 159
    args: Optional[List[str]] = None                                   # line 160
    env: Optional[Dict[str, str]] = None                               # line 161
    auth_credential: Optional[AuthCredential] = None                   # line 167
    auth_type: Optional[AuthScheme] = None                             # line 168
    auth_config: Dict[str, Any] = field(default_factory=dict)          # line 169
    token_supplier: Optional[Callable[[], Optional[str]]] = None       # line 171
    transport: str = "auto"                                            # line 174
    headers: Dict[str, str] = field(default_factory=dict)              # line 181
    header_provider: Optional[Callable] = None                         # line 183
    timeout: float = 30.0                                              # line 205
    rate_limit_max_retries: int = 2                                    # line 214
    rate_limit_max_wait: float = 60.0                                  # line 215
    quic_config: Any = None                                            # line 222
    async def get_headers(self, context=None) -> Dict[str, str]: ...   # line 224
    def validate_transport(self) -> None: ...                          # line 259
    @classmethod
    def from_yaml_config(cls, config_dict, config_abs_path="") -> 'MCPClientConfig': ...  # line 277

# parrot/mcp/oauth.py:29-33
class TokenStore:
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

# parrot/mcp/oauth.py:70
class VaultTokenStore(TokenStore):
    @staticmethod
    def _vault_name(user_id: str, server_name: str) -> str: ...   # line 88
    async def get(self, user_id, server_name) -> Optional[Dict]: ...  # line 104
    async def set(self, user_id, server_name, token) -> None: ...     # line 128
    async def delete(self, user_id, server_name) -> None: ...         # line 150

# parrot/mcp/oauth.py:282
class OAuthManager:  # TO BE DEPRECATED
    def __init__(self, *, user_id, server_name, client_id, auth_url, token_url,
                 scopes, redirect_host="127.0.0.1", redirect_port=8765,
                 redirect_path="/mcp/oauth/callback", token_store, client_secret=None,

…(truncated)…
