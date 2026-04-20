# Feature Specification: MCP Mixin Helper Handler

**Feature ID**: FEAT-110
**Date**: 2026-04-19
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `MCPEnabledMixin` class provides convenience methods (`add_perplexity_mcp_server`,
`add_fireflies_mcp_server`, `add_chrome_devtools_mcp_server`, `add_google_maps_mcp_server`,
`add_alphavantage_mcp_server`, `add_genmedia_mcp_servers`, etc.) that let backend code
wire up MCP servers without knowing transport, command, or env-var details.

However, there is **no HTTP interface** for frontends to:

1. **Discover** which pre-built MCP server helpers exist and what parameters each
   requires (e.g. Perplexity needs `api_key`; Chrome DevTools needs `browser_url`).
2. **Activate** a pre-built MCP server on the user's session-scoped `ToolManager`
   by providing only the required parameters.
3. **Store credentials securely** in the user's Vault so they persist across sessions.
4. **Restore** previously-configured MCP servers automatically when the user starts
   a new conversation with the same agent.

Today the frontend must know the raw `MCPServerConfig` schema and send it via
the existing PATCH endpoint — defeating the purpose of the convenience helpers.

### Goals

- **G1**: Expose a `GET` endpoint that returns a catalog of all available pre-built
  MCP server helpers with their required/optional parameters and descriptions.
- **G2**: Expose a `POST` endpoint that activates a selected MCP server on the
  user's session-scoped `ToolManager`, calling the corresponding `add_*_mcp_server`
  helper method under the hood.
- **G3**: Integrate with the existing `CredentialsHandler` Vault to securely store
  the credentials (API keys, tokens) the user provides when activating an MCP server.
- **G4**: Persist the list of user-activated MCP servers to DocumentDB so they can
  be automatically restored in future sessions.
- **G5**: On session init (PATCH), restore previously-saved MCP server configurations
  from the persistence layer, re-connecting them to the `ToolManager`.

### Non-Goals (explicitly out of scope)

- Building a UI — this spec covers only the backend API and persistence layer.
- Adding new MCP server helper methods — this feature exposes the *existing* ones.
- OAuth2 flow management for MCP servers — that's already handled by `add_oauth_mcp_server`.
- Modifying the existing PATCH/POST flow in `AgentTalk` beyond adding the restore hook.

---

## 2. Architectural Design

### Overview

Introduce an **MCP Server Registry** — a declarative catalog that describes each
pre-built helper method's name, required parameters, optional parameters with
defaults, and human-readable description. The registry is built by introspecting
the `MCPEnabledMixin` class and augmenting with metadata annotations.

A new HTTP handler (`MCPHelperHandler`) provides:
- `GET /api/v1/agents/chat/{agent_id}/mcp-servers` — returns the catalog.
- `POST /api/v1/agents/chat/{agent_id}/mcp-servers` — activates one server.
- `GET /api/v1/agents/chat/{agent_id}/mcp-servers/active` — lists active servers.
- `DELETE /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name}` — deactivates.

Credentials flow through the existing `CredentialsHandler` Vault infrastructure.
A persistence layer stores per-user, per-agent MCP configs in DocumentDB.

### Component Diagram

```
Frontend
   │
   ├─ GET  .../mcp-servers          → MCPHelperHandler.get()
   │                                   └─ MCPServerRegistry.list_servers()
   │
   ├─ POST .../mcp-servers          → MCPHelperHandler.post()
   │     { "server": "perplexity",    └─ 1. Validate params
   │       "params": {"api_key":"x"}}    2. Store creds in Vault
   │                                     3. Call add_*_mcp_server on ToolManager
   │                                     4. Persist config to DocumentDB
   │
   ├─ GET  .../mcp-servers/active   → MCPHelperHandler.get_active()
   │                                   └─ Read from session ToolManager
   │
   └─ DELETE .../mcp-servers/{name} → MCPHelperHandler.delete()
                                       └─ 1. Remove from ToolManager
                                          2. Remove from DocumentDB
                                          3. Optionally remove Vault cred

AgentTalk PATCH (existing)
   └─ _setup_agent_tools()
       └─ NEW: _restore_user_mcp_servers()
           └─ Read user's saved configs from DocumentDB
               └─ For each: retrieve creds from Vault, call add_*_mcp_server
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MCPEnabledMixin` | reads | Introspects `add_*_mcp_server` methods for registry |
| `MCPToolManagerMixin` | calls | `add_mcp_server()` to register tools on ToolManager |
| `AgentTalk.patch()` | extends | Adds MCP server restore step in `_setup_agent_tools` |
| `CredentialsHandler` / Vault | calls | Stores/retrieves API keys and secrets |
| `DocumentDb` | calls | Persists user MCP server configurations |
| `UserObjectsHandler` | extends | New route registration alongside existing ones |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum


class MCPParamType(str, Enum):
    """Type hint for MCP server parameter."""
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    SECRET = "secret"  # Signals frontend to mask input and store in Vault


class MCPServerParam(BaseModel):
    """Describes a single parameter for an MCP server helper."""
    name: str
    type: MCPParamType = MCPParamType.STRING
    required: bool = True
    default: Optional[Any] = None
    description: str = ""


class MCPServerDescriptor(BaseModel):
    """Catalog entry for a pre-built MCP server helper."""
    name: str = Field(..., description="Server slug, e.g. 'perplexity'")
    display_name: str = Field(..., description="Human-friendly name")
    description: str = Field(..., description="What this MCP server does")
    method_name: str = Field(..., description="MCPEnabledMixin method to call")
    params: List[MCPServerParam] = Field(default_factory=list)
    category: str = Field(default="general", description="e.g. 'search', 'media', 'dev-tools'")


class UserMCPServerConfig(BaseModel):
    """Persisted configuration for a user-activated MCP server."""
    server_name: str = Field(..., description="Registry slug")
    agent_id: str
    user_id: str
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret params (secrets stored in Vault)"
    )
    vault_credential_name: Optional[str] = Field(
        None, description="Name of the Vault credential holding secrets"
    )
    active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ActivateMCPServerRequest(BaseModel):
    """POST body for activating an MCP server."""
    server: str = Field(..., description="Registry slug, e.g. 'perplexity'")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters including secrets"
    )
```

### New Public Interfaces

```python
# parrot/mcp/registry.py
class MCPServerRegistry:
    """Catalog of pre-built MCP server helpers available for user activation."""

    def list_servers(self) -> List[MCPServerDescriptor]:
        """Return all registered MCP server descriptors."""
        ...

    def get_server(self, name: str) -> Optional[MCPServerDescriptor]:
        """Look up a single server descriptor by slug."""
        ...

    def validate_params(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate user-supplied params against the descriptor schema.
        Returns cleaned params dict. Raises ValueError on missing required params.
        """
        ...


# parrot/handlers/mcp_helper.py
class MCPHelperHandler(BaseView):
    """HTTP handler for MCP server discovery, activation, and management."""

    async def get(self) -> web.Response: ...
    async def post(self) -> web.Response: ...
    async def delete(self) -> web.Response: ...


# parrot/handlers/mcp_persistence.py
class MCPPersistenceService:
    """Handles saving/loading user MCP server configs to/from DocumentDB."""

    async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None: ...
    async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[UserMCPServerConfig]: ...
    async def remove_user_mcp_config(self, user_id: str, agent_id: str, server_name: str) -> bool: ...
```

---

## 3. Module Breakdown

### Module 1: MCP Server Registry
- **Path**: `parrot/mcp/registry.py`
- **Responsibility**: Declarative catalog of all `add_*_mcp_server` helpers with
  parameter metadata. Provides `list_servers()`, `get_server()`, `validate_params()`.
- **Depends on**: `MCPEnabledMixin` (introspection only, no runtime calls)

### Module 2: MCP Persistence Service
- **Path**: `parrot/handlers/mcp_persistence.py`
- **Responsibility**: CRUD for `UserMCPServerConfig` documents in DocumentDB.
  Provides save, load, and remove operations scoped by `(user_id, agent_id)`.
- **Depends on**: `DocumentDb`, `UserMCPServerConfig` model

### Module 3: MCP Helper HTTP Handler
- **Path**: `parrot/handlers/mcp_helper.py`
- **Responsibility**: HTTP endpoints for catalog listing, server activation
  (with Vault credential storage), active server listing, and deactivation.
- **Depends on**: Module 1 (Registry), Module 2 (Persistence), `CredentialsHandler` Vault utils

### Module 4: Session Restore Hook
- **Path**: `parrot/handlers/agent.py` (modify existing)
- **Responsibility**: Add `_restore_user_mcp_servers()` method to `AgentTalk`
  that runs during `_setup_agent_tools()`. Loads persisted configs, retrieves
  Vault credentials, and calls the appropriate `add_*_mcp_server` helper on
  the session ToolManager.
- **Depends on**: Module 1 (Registry), Module 2 (Persistence), Vault utils

### Module 5: Route Registration
- **Path**: `parrot/handlers/__init__.py` or route setup module (modify existing)
- **Responsibility**: Wire `MCPHelperHandler` into the aiohttp route table.
- **Depends on**: Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_registry_list_servers` | Module 1 | Returns all descriptors with correct params |
| `test_registry_get_server` | Module 1 | Finds server by slug, returns None for unknown |
| `test_registry_validate_params_ok` | Module 1 | Accepts valid params |
| `test_registry_validate_params_missing` | Module 1 | Raises ValueError for missing required param |
| `test_registry_param_types` | Module 1 | Correctly identifies SECRET vs STRING params |
| `test_persistence_save_load` | Module 2 | Round-trip save/load from DocumentDB |
| `test_persistence_remove` | Module 2 | Removes config, subsequent load returns empty |
| `test_persistence_scoping` | Module 2 | Configs isolated by user_id + agent_id |
| `test_helper_get_catalog` | Module 3 | GET returns JSON catalog with all servers |
| `test_helper_post_activate` | Module 3 | POST activates server, stores creds, persists config |
| `test_helper_post_missing_param` | Module 3 | POST returns 400 for missing required param |
| `test_helper_delete_deactivate` | Module 3 | DELETE removes server from ToolManager and DB |
| `test_restore_hook` | Module 4 | Session init restores previously-saved servers |
| `test_restore_hook_vault_missing` | Module 4 | Graceful degradation when Vault cred is gone |

### Integration Tests

| Test | Description |
|---|---|
| `test_activate_and_restore_flow` | POST to activate, new PATCH restores, verify tools present |
| `test_delete_and_restore_empty` | DELETE server, new PATCH should not restore it |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_registry():
    """Pre-populated MCPServerRegistry for testing."""
    return MCPServerRegistry()


@pytest.fixture
def sample_activate_payload():
    return {
        "server": "perplexity",
        "params": {"api_key": "test-key-123"}
    }
```

---

## 5. Acceptance Criteria

- [ ] `GET /api/v1/agents/chat/{agent_id}/mcp-servers` returns JSON catalog of all pre-built MCP servers with name, description, params (type, required, default)
- [ ] `POST /api/v1/agents/chat/{agent_id}/mcp-servers` activates a server on the session ToolManager given a registry slug and parameters
- [ ] Secret parameters (api_key, etc.) are stored in the user's Vault via existing `encrypt_credential` utilities, not in DocumentDB plaintext
- [ ] Non-secret configuration is persisted to DocumentDB under `user_mcp_configs` collection
- [ ] On `PATCH /api/v1/agents/chat/{agent_id}` (session init), previously-saved MCP servers are automatically restored and connected
- [ ] `DELETE /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name}` removes the server from ToolManager, DocumentDB, and optionally Vault
- [ ] `GET /api/v1/agents/chat/{agent_id}/mcp-servers/active` returns the list of currently active MCP servers in the session
- [ ] All unit tests pass
- [ ] No breaking changes to existing PATCH/POST AgentTalk behavior
- [ ] Registry correctly reflects all existing `add_*_mcp_server` methods from `MCPEnabledMixin`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot.mcp.integration import MCPEnabledMixin  # verified: parrot/mcp/integration.py:1087
from parrot.mcp.integration import MCPServerConfig   # re-exported, actual class at parrot/mcp/config.py:16
from parrot.mcp.client import MCPClientConfig         # verified: parrot/mcp/client.py:130
from parrot.tools.manager import ToolManager          # verified: parrot/tools/manager.py
from parrot.tools.mcp_mixin import MCPToolManagerMixin  # verified: parrot/tools/mcp_mixin.py:27
from parrot.handlers.agent import AgentTalk            # verified: parrot/handlers/agent.py:47
from parrot.handlers.user_objects import UserObjectsHandler  # verified: parrot/handlers/user_objects.py:22
from parrot.handlers.credentials import CredentialsHandler   # verified: parrot/handlers/credentials.py:71
from parrot.handlers.credentials_utils import encrypt_credential, decrypt_credential  # verified: parrot/handlers/credentials_utils.py
from parrot.interfaces.documentdb import DocumentDb    # verified: parrot/interfaces/documentdb.py
from navigator.views import BaseView                   # verified: used in agent.py:31
from navigator_auth.decorators import is_authenticated, user_session  # verified: agent.py:22
from navigator_session import get_session              # verified: agent.py:21
from navigator_session.vault.config import get_active_key_id, load_master_keys  # verified: credentials.py:41
```

### Existing Class Signatures

```python
# parrot/mcp/integration.py
class MCPEnabledMixin:  # line 1087
    _mcp_initialized: bool  # line 1092
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]:  # line 1094
    async def add_perplexity_mcp_server(self, api_key: str, name: str = "perplexity", **kwargs) -> List[str]:  # line 1161
    async def add_fireflies_mcp_server(self, api_key: str, **kwargs) -> List[str]:  # line 1171
    async def add_chrome_devtools_mcp_server(self, browser_url: str = "http://127.0.0.1:9222", name: str = "chrome-devtools", **kwargs) -> List[str]:  # line 1193
    async def add_google_maps_mcp_server(self, name: str = "google-maps", **kwargs) -> List[str]:  # line 1216
    async def add_quic_mcp_server(self, name: str, host: str, port: int, cert_path: Optional[str] = None, **kwargs) -> List[str]:  # line 1236
    async def add_websocket_mcp_server(self, name: str, url: str, auth_type: Optional[str] = None, auth_config: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, **kwargs) -> List[str]:  # line 1248
    async def remove_mcp_server(self, server_name: str):  # line 1283
    async def reconfigure_mcp_server(self, config: MCPServerConfig) -> List[str]:  # line 1286
    async def add_alphavantage_mcp_server(self, api_key: Optional[str] = None, name: str = "alphavantage", **kwargs) -> List[str]:  # line 1351
    async def add_genmedia_mcp_servers(self, **kwargs) -> Dict[str, List[str]]:  # line 1370
    def list_mcp_servers(self) -> List[str]:  # line 1337

# parrot/mcp/config.py — MCPServerConfig (server-side config)
@dataclass
class MCPServerConfig:  # line 16
    name: str  # line 18
    transport: str = "stdio"  # line 23
    host: str = "localhost"  # line 25
    port: int = 8080  # line 26
    allowed_tools: Optional[List[str]] = None  # line 29
    blocked_tools: Optional[List[str]] = None  # line 30

# parrot/mcp/client.py — MCPClientConfig (client-side config, used by add_mcp_server)
@dataclass
class MCPClientConfig:  # line 130
    name: str  # line 154
    url: Optional[str] = None  # line 157
    command: Optional[str] = None  # line 158
    args: Optional[List[str]] = None  # line 159
    env: Optional[Dict[str, str]] = None  # line 160
    auth_type: Optional[AuthScheme] = None  # line 167
    auth_config: Dict[str, Any]  # line 168
    transport: str = "auto"  # line 173
    headers: Dict[str, str]  # line 180
    timeout: float = 30.0  # line 204
    startup_delay: float = 0.5  # line 206

# parrot/tools/mcp_mixin.py
class MCPToolManagerMixin:  # line 27
    _mcp_clients: Dict[str, 'MCPClient']  # line 48
    _mcp_configs: Dict[str, 'MCPServerConfig']  # line 49
    async def add_mcp_server(self, config: 'MCPServerConfig', context: Optional['ReadonlyContext'] = None) -> List[str]:  # line 52
    def list_mcp_servers(self) -> List[str]:  # not shown, referenced from MCPEnabledMixin line 1338

# parrot/handlers/agent.py
class AgentTalk(BaseView):  # line 47
    async def patch(self):  # line 1391
    async def _setup_agent_tools(self, agent: AbstractBot, data: Dict[str, Any], request_session: Any) -> Union[web.Response, None]:  # line 934
    async def _filter_mcp_servers_for_user(self, mcp_server_configs: list) -> list:  # line 287

# parrot/handlers/user_objects.py
class UserObjectsHandler:  # line 22
    def get_session_key(self, agent_name: str, manager_type: str) -> str:  # line 50
    async def configure_tool_manager(self, data, request_session, agent_name=None) -> tuple:  # line 96
    async def _add_mcp_servers_to_tool_manager(self, tool_manager: ToolManager, mcp_configs: list) -> None:  # line 64

# parrot/handlers/credentials.py
class CredentialsHandler(BaseView):  # line 71
    COLLECTION: str = "user_credentials"  # line 83
    SESSION_PREFIX: str = "_credentials:"  # line 84
    def _get_user_id(self) -> str:  # line 90
    def _session_key(self, name: str) -> str:  # line 111
    def _set_session_credential(self, name: str, credential_dict: dict) -> None:  # line 122
    async def get(self) -> web.Response:  # line 164
    # Routes: GET/POST/PUT/DELETE at /api/v1/users/credentials[/{name}]

# parrot/handlers/credentials_utils.py
def encrypt_credential(...) -> ...:  # AES encryption wrapper
def decrypt_credential(...) -> ...:  # AES decryption wrapper

# parrot/interfaces/documentdb.py
class DocumentDb:  # async context manager
    async def read_one(self, collection, filter) -> Optional[dict]: ...
    async def read_many(self, collection, filter) -> list: ...
    async def insert_one(self, collection, document) -> ...: ...
    async def update_one(self, collection, filter, update) -> ...: ...
    async def delete_one(self, collection, filter) -> ...: ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MCPServerRegistry` | `MCPEnabledMixin` | Introspects `add_*` methods | `integration.py:1087-1399` |
| `MCPHelperHandler.post()` | `ToolManager.add_mcp_server()` | Calls via registry dispatch | `mcp_mixin.py:52` |
| `MCPHelperHandler.post()` | `CredentialsHandler` Vault utils | `encrypt_credential()` | `credentials_utils.py` |
| `MCPHelperHandler.post()` | `MCPPersistenceService` | `save_user_mcp_config()` | New |
| `AgentTalk._setup_agent_tools()` | `MCPPersistenceService` | `load_user_mcp_configs()` | New hook |
| `MCPHelperHandler.delete()` | `MCPToolManagerMixin` | `remove_mcp_server()` | `mcp_mixin.py` via `MCPEnabledMixin:1283` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.mcp.registry`~~ — **does not exist yet**; must be created
- ~~`parrot.handlers.mcp_helper`~~ — **does not exist yet**; must be created
- ~~`parrot.handlers.mcp_persistence`~~ — **does not exist yet**; must be created
- ~~`MCPServerRegistry` class~~ — does not exist; servers tracked in ToolManager's `_mcp_clients` dict only
- ~~`MCPEnabledMixin.get_available_helpers()`~~ — no such introspection method exists
- ~~`ToolManager.add_tool_for_user(user_id, tool)`~~ — no user-scoped tool registration; scoping via session
- ~~`AgentTalk._restore_user_mcp_servers()`~~ — does not exist yet; must be added
- ~~`parrot.vault.*`~~ — Vault lives in `navigator_session.vault`, not parrot-internal
- ~~`CredentialsHandler.store_mcp_credential()`~~ — no such method; use `encrypt_credential` utils directly
- ~~`user_mcp_configs` DocumentDB collection~~ — does not exist yet; must be created via persistence service

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Handler pattern**: Follow `CredentialsHandler` (same `@is_authenticated()` + `@user_session()` decorators, same `BaseView` base class). See `credentials.py:69-71`.
- **Vault credential storage**: Use `encrypt_credential` / `decrypt_credential` from `credentials_utils.py`. Follow the same key-derivation pattern as `CredentialsHandler._load_vault_keys()`.
- **DocumentDB persistence**: Use `async with DocumentDb() as db:` context manager pattern (see `credentials.py:191`).
- **Session scoping**: Use `UserObjectsHandler.get_session_key(agent_name, ...)` for session key naming.
- **Logging**: Use `self.logger = logging.getLogger(self._logger_name)` pattern.
- **MCPClientConfig vs MCPServerConfig**: The `create_*_mcp_server` factory functions return `MCPClientConfig` (aliased as `MCPServerConfig` in `integration.py`). The `MCPServerConfig` in `config.py` is the *server-side* config. When calling `ToolManager.add_mcp_server()`, pass `MCPClientConfig` instances.

### Registry Construction Strategy

The registry should be declarative, not reflection-based. Each entry explicitly maps
a slug to a `MCPEnabledMixin` method name and declares its parameter schema. This avoids
fragility from signature changes and lets us add descriptions/categories that can't be
inferred from code. Example:

```python
REGISTRY = [
    MCPServerDescriptor(
        name="perplexity",
        display_name="Perplexity AI",
        description="Web search, conversational AI, deep research, and reasoning via Perplexity models",
        method_name="add_perplexity_mcp_server",
        category="search",
        params=[
            MCPServerParam(name="api_key", type=MCPParamType.SECRET, required=True,
                           description="Perplexity API key from perplexity.ai/account/api"),
        ],
    ),
    # ...
]
```

### Credential Isolation

Secret params (type=`SECRET`) are:
1. Extracted from the request payload.
2. Stored in Vault under a deterministic name: `mcp_{server_name}_{agent_id}`.
3. The `UserMCPServerConfig` document references the Vault credential name but
   never contains the secret value.
4. On restore, the secret is fetched from Vault and passed to the helper method.

### Activation Flow (detailed)

1. Frontend `POST`s `{ "server": "perplexity", "params": {"api_key": "sk-..."} }`.
2. Handler looks up `"perplexity"` in `MCPServerRegistry`.
3. Registry validates params (api_key required, type SECRET).
4. Handler separates secret params from non-secret params.
5. Secret params → Vault via `encrypt_credential` + DocumentDB persistence.
6. Handler resolves the `create_*_mcp_server` factory function and calls it.
7. Resulting `MCPClientConfig` → `ToolManager.add_mcp_server(config)`.
8. Non-secret config + vault_credential_name → `MCPPersistenceService.save_user_mcp_config()`.
9. Response: `200 OK` with registered tool names.

### Known Risks / Gotchas

- **Factory function aliasing**: `MCPEnabledMixin.add_perplexity_mcp_server` internally
  calls `create_perplexity_mcp_server` then `self.add_mcp_server(config)`. For the
  handler, we should call the `create_*` factory directly and pass the config to
  `ToolManager.add_mcp_server()` — the mixin's `self.tool_manager` won't exist on
  the handler. This is the correct approach.
- **Session ToolManager lifetime**: The ToolManager lives only in the session (Redis).
  If the session expires, the MCP connections are gone. The persistence layer ensures
  they can be restored, but running MCP processes (stdio) will be lost.
- **npx-based servers**: Perplexity, Fireflies, Chrome DevTools, Google Maps all use
  `npx` subprocess — these have `startup_delay` and can fail if npx is not available.
  The handler should catch connection errors and return them gracefully.
- **Vault key rotation**: If Vault master keys rotate, existing encrypted credentials
  must be re-encrypted. This is handled by `CredentialsHandler` already — follow the
  same `master_keys` dict pattern for decryption with any key_id.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-session` | existing | Vault encryption, session management |
| `navigator-auth` | existing | Authentication decorators |
| `pydantic` | existing | Data models |
| `aiohttp` | existing | HTTP handler |

---

## 8. Open Questions

- [ ] Should the `DELETE` endpoint also remove the Vault credential, or leave it for
      the user to manage separately via `CredentialsHandler`? — *Owner: Jesus*
- [ ] Should we support activating the same MCP server multiple times with different
      credentials (e.g., two Perplexity accounts)? If yes, the slug must include a
      user-provided alias. — *Owner: Jesus*
- [ ] Should the restore hook be opt-in per agent (via agent config) or always-on? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree)
- All modules are tightly coupled (registry feeds handler, handler calls persistence,
  restore hook calls both). Sequential execution avoids merge conflicts.
- **Cross-feature dependencies**: None — this feature builds on existing stable
  components (`MCPEnabledMixin`, `CredentialsHandler`, `AgentTalk`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-19 | Jesus Lara | Initial draft |
