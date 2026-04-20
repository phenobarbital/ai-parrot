# TASK-771: MCP Helper HTTP Handler — Discovery, Activation & Management Endpoints

**Feature**: FEAT-110 — MCP Mixin Helper Handler
**Spec**: `sdd/specs/mcp-mixin-helper-handler.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-769, TASK-770
**Assigned-to**: unassigned

---

## Context

This is the main HTTP handler task. It exposes four endpoints that let frontends
discover available MCP server helpers, activate them on the user's session-scoped
ToolManager, list active servers, and deactivate them. This is the core deliverable
that bridges the frontend to the `MCPEnabledMixin` convenience methods.

Implements spec Section 3, Module 3.

---

## Scope

- Implement `MCPHelperHandler(BaseView)` in `parrot/handlers/mcp_helper.py` with:
  - `GET /api/v1/agents/chat/{agent_id}/mcp-servers` — returns the full catalog from `MCPServerRegistry`
  - `POST /api/v1/agents/chat/{agent_id}/mcp-servers` — activates a server:
    1. Validate params via `MCPServerRegistry.validate_params()`
    2. Separate secret params (type=SECRET) from non-secret params
    3. Store secret params in Vault using `encrypt_credential` + DocumentDB (following `CredentialsHandler` pattern)
    4. Call the corresponding `create_*_mcp_server` factory function to build config
    5. Call `ToolManager.add_mcp_server(config)` on the session-scoped ToolManager
    6. Persist non-secret config via `MCPPersistenceService.save_user_mcp_config()`
    7. Return `200` with registered tool names
  - `GET /api/v1/agents/chat/{agent_id}/mcp-servers/active` — lists active MCP servers from session ToolManager
  - `DELETE /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name}` — deactivates:
    1. Remove from session ToolManager via `remove_mcp_server()`
    2. Soft-delete from DocumentDB via `MCPPersistenceService`
    3. Return `200` with confirmation
- Apply `@is_authenticated()` and `@user_session()` decorators (same as `CredentialsHandler`).
- Implement `setup_mcp_helper_routes(app)` function for route registration.
- Write unit tests.

**NOT in scope**: Session restore hook (TASK-772), route registration in manager.py (TASK-773).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/mcp_helper.py` | CREATE | MCPHelperHandler + setup_mcp_helper_routes |
| `tests/unit/test_mcp_helper_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web  # verified: used in agent.py:16
from navconfig.logging import logging  # verified: used in agent.py:20
from navigator.views import BaseView  # verified: used in agent.py:31
from navigator_auth.decorators import is_authenticated, user_session  # verified: agent.py:22
from navigator_session import get_session  # verified: agent.py:21

from parrot.mcp.registry import (  # created by TASK-769
    MCPServerRegistry,
    MCPServerDescriptor,
    MCPParamType,
    ActivateMCPServerRequest,
    UserMCPServerConfig,
)
from parrot.handlers.mcp_persistence import MCPPersistenceService  # created by TASK-770
from parrot.tools.manager import ToolManager  # verified: parrot/tools/manager.py
from parrot.interfaces.documentdb import DocumentDb  # verified: parrot/interfaces/documentdb.py
from parrot.handlers.credentials_utils import (  # verified: parrot/handlers/credentials_utils.py
    encrypt_credential,
    decrypt_credential,
)

# Factory functions for building MCPClientConfig — import the specific ones needed
from parrot.mcp.integration import (
    create_perplexity_mcp_server,     # line 970
    create_fireflies_mcp_server,       # line 851
    create_chrome_devtools_mcp_server, # line 883
    create_google_maps_mcp_server,     # line 942
    create_alphavantage_mcp_server,    # line 1055
    create_quic_mcp_server,            # line 1013
    create_websocket_mcp_server,       # line 775
)

# Vault key loading (same pattern as credentials.py)
from navigator_session.vault.config import get_active_key_id, load_master_keys  # verified: credentials.py:41
```

### Existing Signatures to Use
```python
# parrot/handlers/credentials_utils.py
def encrypt_credential(credential: dict, key_id: int, master_key: bytes) -> str:  # line 19
def decrypt_credential(encrypted: str, master_keys: dict[int, bytes]) -> dict:  # line 52

# parrot/handlers/credentials.py — vault key loading pattern (line 49-66)
def _load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]:
    master_keys = load_master_keys()
    active_key_id = get_active_key_id()
    active_key = master_keys[active_key_id]
    return active_key_id, active_key, master_keys

# parrot/tools/mcp_mixin.py — ToolManager's MCP methods
class MCPToolManagerMixin:  # line 27
    _mcp_clients: Dict[str, 'MCPClient']  # line 48
    async def add_mcp_server(self, config: 'MCPServerConfig', context=None) -> List[str]:  # line 52
    # remove_mcp_server is called through MCPEnabledMixin (line 1283) which delegates to tool_manager

# parrot/handlers/credentials.py — route setup pattern (line 506-523)
def setup_credentials_routes(app: web.Application) -> None:
    app.router.add_route("*", "/api/v1/users/credentials", CredentialsHandler)
    app.router.add_route("*", "/api/v1/users/credentials/{name}", CredentialsHandler)

# parrot/handlers/user_objects.py — session key pattern (line 50)
class UserObjectsHandler:
    def get_session_key(self, agent_name: str, manager_type: str) -> str:  # line 50
        prefix = f"{agent_name}_" if agent_name else ""
        return f"{prefix}{manager_type}"

# Session ToolManager retrieval pattern (from AgentTalk PATCH, line 1459-1461):
# request_session = self.request.session or await get_session(self.request)
# session_key = f"{agent_name}_tool_manager"
# tool_manager = request_session.get(session_key)
```

### Does NOT Exist
- ~~`parrot.handlers.mcp_helper`~~ — does not exist yet; this task creates it
- ~~`MCPHelperHandler`~~ — does not exist; this task creates it
- ~~`setup_mcp_helper_routes`~~ — does not exist; this task creates it
- ~~`ToolManager.remove_mcp_server()`~~ — method is on `MCPToolManagerMixin`, mixed into `ToolManager`; verify at runtime
- ~~`CredentialsHandler.store_mcp_credential()`~~ — no such method; use `encrypt_credential` directly
- ~~`AgentTalk.mcp_helper`~~ — no such attribute; the handler is a separate view

---

## Implementation Notes

### Factory Function Dispatch
The handler needs a mapping from registry slug to factory function. Build a dict:

```python
_FACTORY_MAP = {
    "perplexity": create_perplexity_mcp_server,
    "fireflies": create_fireflies_mcp_server,
    "chrome-devtools": create_chrome_devtools_mcp_server,
    "google-maps": create_google_maps_mcp_server,
    "alphavantage": create_alphavantage_mcp_server,
    "quic": create_quic_mcp_server,
    "websocket": create_websocket_mcp_server,
}
```

### Credential Storage Pattern
For secret params, store them in the same DocumentDB collection used by
`CredentialsHandler` (`user_credentials`) under a deterministic name:
`mcp_{server_name}_{agent_id}`. This lets the restore hook (TASK-772) retrieve
them using the same `decrypt_credential` path.

```python
# Vault storage (same pattern as CredentialsHandler POST)
active_key_id, active_key, _ = _load_vault_keys()
encrypted = encrypt_credential(secret_params, active_key_id, active_key)
# Store encrypted blob in DocumentDB under user_credentials collection
```

### Session ToolManager Access
The POST handler needs the session-scoped ToolManager. Retrieve it from session:
```python
session = self.request.session or await get_session(self.request)
agent_id = self.request.match_info.get("agent_id")
session_key = f"{agent_id}_tool_manager"
tool_manager = session.get(session_key)
if tool_manager is None:
    tool_manager = ToolManager()
    session[session_key] = tool_manager
```

### Route Registration
```python
def setup_mcp_helper_routes(app: web.Application) -> None:
    base = "/api/v1/agents/chat/{agent_id}/mcp-servers"
    app.router.add_route("GET", base, MCPHelperHandler)
    app.router.add_route("POST", base, MCPHelperHandler)
    app.router.add_route("GET", f"{base}/active", MCPHelperHandler)
    app.router.add_route("DELETE", f"{base}/{{server_name}}", MCPHelperHandler)
```

Note: aiohttp `BaseView` uses `add_route("*", ...)` pattern — the handler dispatches
by HTTP method internally. Consider using separate handler classes for the `/active`
and `/{server_name}` sub-routes, or handle dispatch via `match_info`.

### Key Constraints
- All endpoints must be `@is_authenticated()` + `@user_session()`
- Return JSON via `self.json_response(data, status=NNN)`
- Error responses via `self.error("message", status=NNN)`
- Follow the Pydantic validation pattern from `UserObjectsHandler.configure_tool_manager`
- Log all MCP server activations/deactivations at INFO level

### References in Codebase
- `parrot/handlers/credentials.py` — full CRUD handler pattern with Vault
- `parrot/handlers/agent.py:1391-1478` — PATCH handler, session ToolManager access
- `parrot/handlers/user_objects.py:96-128` — ToolManager configuration from request data

---

## Acceptance Criteria

- [ ] `GET .../mcp-servers` returns JSON array of all server descriptors with params
- [ ] `POST .../mcp-servers` with `{"server":"perplexity","params":{"api_key":"x"}}` activates server, returns tool names
- [ ] `POST .../mcp-servers` with missing required param returns 400 with descriptive error
- [ ] `POST .../mcp-servers` stores secret params encrypted in Vault (not in DocumentDB plaintext)
- [ ] `POST .../mcp-servers` persists non-secret config via `MCPPersistenceService`
- [ ] `GET .../mcp-servers/active` returns list of currently active MCP servers in session
- [ ] `DELETE .../mcp-servers/{server_name}` removes server from ToolManager and soft-deletes from DB
- [ ] All endpoints require authentication (return 401 without valid session)
- [ ] `setup_mcp_helper_routes(app)` registers all routes correctly
- [ ] All tests pass: `pytest tests/unit/test_mcp_helper_handler.py -v`

---

## Test Specification

```python
# tests/unit/test_mcp_helper_handler.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop


class TestMCPHelperHandler:
    """Unit tests for MCPHelperHandler methods."""

    def test_get_catalog_returns_all_servers(self):
        """GET endpoint returns full catalog."""
        # Mock registry and verify response structure
        pass

    def test_post_activate_validates_params(self):
        """POST with missing required param returns 400."""
        pass

    def test_post_activate_stores_secrets_in_vault(self):
        """POST separates secret params and encrypts them."""
        pass

    def test_post_activate_calls_factory_and_adds_to_toolmanager(self):
        """POST calls the correct create_* factory and adds config to ToolManager."""
        pass

    def test_post_activate_persists_config(self):
        """POST calls MCPPersistenceService.save_user_mcp_config."""
        pass

    def test_delete_removes_from_toolmanager_and_db(self):
        """DELETE calls remove on both ToolManager and persistence."""
        pass

    def test_get_active_returns_session_servers(self):
        """GET /active returns servers from session ToolManager."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-769 and TASK-770 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm all imports and signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-771-mcp-helper-http-handler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-19
**Notes**: Implemented MCPHelperHandler (GET catalog, POST activate), MCPActiveHandler (GET active), MCPServerItemHandler (DELETE deactivate), and setup_mcp_helper_routes. Uses factory dispatch via _FACTORY_MAP. Separates secret params, stores in Vault via _store_vault_credential. Persists via MCPPersistenceService. All 24 unit tests pass.

**Deviations from spec**: Used three separate handler classes (MCPHelperHandler, MCPActiveHandler, MCPServerItemHandler) instead of one class with multiple sub-path dispatch — this is cleaner for aiohttp's class-based view pattern. genmedia server returns 400 (no create_* factory exists for it).
