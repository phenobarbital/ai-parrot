---
type: Wiki Overview
title: 'TASK-925: NetSuite MCP Integration Tests'
id: doc:sdd-tasks-completed-task-925-netsuite-mcp-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates the unified test file for the entire FEAT-135 feature.
relates_to:
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.registry
  rel: mentions
---

# TASK-925: NetSuite MCP Integration Tests

**Feature**: FEAT-135 — NetSuite MCP Integration
**Spec**: `sdd/specs/netsuite-mcp-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-922, TASK-923, TASK-924
**Assigned-to**: unassigned

---

## Context

This task creates the unified test file for the entire FEAT-135 feature.
It covers `VaultTokenStore`, `create_netsuite_mcp_server()` factory, URL
construction, token store selection, registry entry, and factory map integration.

Implements Spec §4 (Test Specification).

---

## Scope

- Create `tests/mcp/test_netsuite_mcp.py` with all unit tests for FEAT-135
- Test `VaultTokenStore`: get/set/delete with mocked vault_utils, error handling
- Test `create_netsuite_mcp_server()`: URL construction, scope, transport, token_supplier, _ensure_oauth_token
- Test registry: descriptor exists, params correct, factory map entry
- Test config pipeline: end-to-end config creation verifying all fields

**NOT in scope**: Integration tests against a real NetSuite instance (requires live OAuth)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/mcp/test_netsuite_mcp.py` | CREATE | All unit tests for FEAT-135 |
| `tests/mcp/__init__.py` | CREATE (if missing) | Package init for test discovery |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.mcp.oauth import VaultTokenStore, TokenStore, InMemoryTokenStore
    # verified after TASK-922: packages/ai-parrot/src/parrot/mcp/oauth.py

from parrot.mcp.integration import create_netsuite_mcp_server
    # verified after TASK-923: packages/ai-parrot/src/parrot/mcp/integration.py

from parrot.mcp.registry import MCPServerRegistry, get_factory_map
    # verified: packages/ai-parrot/src/parrot/mcp/registry.py:351, :439
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/oauth.py:560
class TokenStore:
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

# After TASK-922:
class VaultTokenStore(TokenStore):
    @staticmethod
    def _vault_name(server_name: str, user_id: str) -> str: ...
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

# After TASK-923:
# create_netsuite_mcp_server(*, account_id, client_id, user_id, token_store=None, ...) -> MCPServerConfig

# packages/ai-parrot/src/parrot/mcp/registry.py:351
class MCPServerRegistry:
    def list_servers(self) -> List[MCPServerDescriptor]: ...     # line 365
    def get_server(self, name: str) -> Optional[MCPServerDescriptor]: ...  # line 373
    def validate_params(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]: ...  # line 387

# packages/ai-parrot/src/parrot/mcp/registry.py:439
def get_factory_map() -> Dict[str, Any]: ...
```

### Does NOT Exist

- ~~`parrot.mcp.integration.MCPEnabledMixin` (for direct instantiation in tests)~~ — it's a mixin, not standalone; test via `create_netsuite_mcp_server()` directly
- ~~`parrot.mcp.netsuite`~~ — no NetSuite-specific module; code is in `integration.py` and `oauth.py`
- ~~`parrot.mcp.integration.NETSUITE_MCP_URL`~~ — may or may not be exported; test URL construction through the factory return value, not the constant directly

---

## Implementation Notes

### Pattern to Follow

Check existing test files in `tests/` for project conventions:

```bash
find tests/ -name "test_*.py" -path "*/mcp/*" | head -5
```

Use `pytest` with `pytest-asyncio` for async tests. Mock `vault_utils` functions
rather than hitting a real database.

### Test Organization

```python
# tests/mcp/test_netsuite_mcp.py

import pytest
from unittest.mock import AsyncMock, patch

# --- Fixtures ---

@pytest.fixture
def vault_store():
    from parrot.mcp.oauth import VaultTokenStore
    return VaultTokenStore()

@pytest.fixture
def sample_token():
    return {
        "access_token": "test-access",
        "refresh_token": "test-refresh",
        "expires_at": 9999999999,
        "token_type": "Bearer",
    }

# --- VaultTokenStore Tests ---

class TestVaultTokenStore:
    @pytest.mark.asyncio
    async def test_set_stores_credential(self, vault_store, sample_token): ...
    @pytest.mark.asyncio
    async def test_get_retrieves_credential(self, vault_store, sample_token): ...
    @pytest.mark.asyncio
    async def test_get_returns_none_on_missing(self, vault_store): ...
    @pytest.mark.asyncio
    async def test_get_returns_none_on_runtime_error(self, vault_store): ...
    @pytest.mark.asyncio
    async def test_delete_removes_credential(self, vault_store): ...
    def test_vault_name_format(self, vault_store): ...

# --- Factory Tests ---

class TestCreateNetsuiteMcpServer:
    def test_url_construction(self): ...
    def test_auth_url_construction(self): ...
    def test_token_url_construction(self): ...
    def test_scopes_are_mcp_only(self): ...
    def test_transport_is_http(self): ...
    def test_name_is_netsuite(self): ...
    def test_token_supplier_is_callable(self): ...
    def test_ensure_token_attached(self): ...
    def test_default_token_store(self): ...
    def test_custom_token_store(self): ...

# --- Registry Tests ---

class TestNetsuiteRegistry:
    def test_netsuite_in_registry(self): ...
    def test_netsuite_params(self): ...
    def test_netsuite_in_factory_map(self): ...
    def test_validate_params_requires_account_id(self): ...
    def test_validate_params_requires_client_id(self): ...
```

### Key Constraints

- All vault operations must be mocked (no real DB)
- Use `pytest.mark.asyncio` for async test methods
- Ensure `tests/mcp/__init__.py` exists for test discovery

---

## Acceptance Criteria

- [ ] `tests/mcp/test_netsuite_mcp.py` exists with all test classes
- [ ] All VaultTokenStore tests pass with mocked vault_utils
- [ ] All factory tests pass verifying URL construction, scope, transport, token hooks
- [ ] All registry tests pass verifying descriptor and factory map
- [ ] Full suite passes: `pytest tests/mcp/test_netsuite_mcp.py -v`
- [ ] No import errors when running tests

---

## Test Specification

The test file IS the deliverable for this task. See the test organization above
and the individual test specifications in TASK-922, TASK-923, and TASK-924.

The complete test file should contain approximately 15-20 test methods covering:
- 6 VaultTokenStore tests
- 8-10 factory tests
- 3-5 registry tests

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/netsuite-mcp-integration.spec.md` for full context
2. **Check dependencies** — verify TASK-922, TASK-923, TASK-924 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm all imports from prior tasks exist
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the test file
6. **Run tests**: `pytest tests/mcp/test_netsuite_mcp.py -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-925-netsuite-mcp-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-04-29
**Notes**: Created tests/mcp/__init__.py and tests/mcp/test_netsuite_mcp.py with 26 tests covering TestVaultTokenStore (7), TestCreateNetsuiteMcpServer (12), TestNetsuiteRegistry (7). All 26 tests pass.

**Deviations from spec**: none
