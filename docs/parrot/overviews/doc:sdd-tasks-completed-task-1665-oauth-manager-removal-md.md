---
type: Wiki Overview
title: 'TASK-1665: OAuthManager Removal & Factory Migration'
id: doc:sdd-tasks-completed-task-1665-oauth-manager-removal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Final migration task. Fully removes the `OAuthManager` class from `parrot/mcp/oauth.py`
relates_to:
- concept: mod:parrot.auth.oauth2.mcp_provider
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.oauth2_config
  rel: mentions
- concept: mod:parrot.mcp.oauth2_storage
  rel: mentions
---

# TASK-1665: OAuthManager Removal & Factory Migration

**Feature**: FEAT-262 — MCP Server OAuth2 Support
**Spec**: `sdd/specs/mcp-server-oauth2-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1659, TASK-1660, TASK-1661, TASK-1662, TASK-1663, TASK-1664
**Assigned-to**: unassigned

---

## Context

Final migration task. Fully removes the `OAuthManager` class from `parrot/mcp/oauth.py`
(no deprecation cycle) and migrates all factory functions (`create_oauth_mcp_server()`,
`create_netsuite_mcp_server()`, `add_oauth_mcp_server()`, etc.) to use the new
`MCPOAuth2Config`-based approach. Also extends `MCPServerDescriptor` with `auth_type`.
Implements spec Module 7.

---

## Scope

- **Remove** `OAuthManager` class from `parrot/mcp/oauth.py` (lines 282-463)
  - Keep `TokenStore`, `InMemoryTokenStore`, `RedisTokenStore`, `VaultTokenStore`, `NetSuiteM2MAuth`
  - Remove the `OAuthManager` import from `__init__.py` if exported
- **Refactor** `create_oauth_mcp_server()` (integration.py:729) to use `MCPOAuth2Config`
  instead of constructing an `OAuthManager`
- **Refactor** `create_netsuite_mcp_server()` (integration.py:802) to use preset + `MCPOAuth2Config`
- **Update** `MCPEnabledMixin.add_oauth_mcp_server()` (integration.py:1358) signature
  and internals to accept `MCPOAuth2Config` or preset-based parameters
- **Update** `add_fireflies_mcp_server()` and other helper methods to keep working
  (Fireflies uses API key, not OAuth2 — verify no changes needed)
- **Extend** `MCPServerDescriptor` with optional `auth_type: str` field
- **Register** `MCPOAuth2Provider` in factory functions via `register_mcp_oauth2_provider()`
- Write tests verifying OAuthManager is gone and factories work with new config

**NOT in scope**: Creating new presets beyond NetSuite (future work).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/oauth.py` | MODIFY | Remove OAuthManager class |
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | Refactor factory functions |
| `packages/ai-parrot/src/parrot/mcp/registry.py` | MODIFY | Add auth_type to MCPServerDescriptor |
| `tests/mcp/test_oauth_manager_removed.py` | CREATE | Verify removal |
| `tests/mcp/test_factory_migration.py` | CREATE | Verify factories work |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current OAuthManager (verified: parrot/mcp/oauth.py:282) — TO BE REMOVED
from parrot.mcp.oauth import OAuthManager  # WILL BE DELETED

# Token stores to KEEP (verified: parrot/mcp/oauth.py:29-170)
from parrot.mcp.oauth import TokenStore, InMemoryTokenStore, RedisTokenStore, VaultTokenStore

# NetSuiteM2MAuth to KEEP (verified: parrot/mcp/oauth.py:175)
from parrot.mcp.oauth import NetSuiteM2MAuth

# Factory functions to refactor (verified: parrot/mcp/integration.py)
from parrot.mcp.integration import create_oauth_mcp_server  # line 729
from parrot.mcp.integration import create_netsuite_mcp_server  # line 802

# New modules from prior tasks
from parrot.mcp.oauth2_config import MCPOAuth2Config, get_mcp_oauth2_preset
from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
from parrot.auth.oauth2.mcp_provider import register_mcp_oauth2_provider
```

### Existing Signatures to Use
```python
# parrot/mcp/integration.py:729 — TO BE REFACTORED
def create_oauth_mcp_server(
    *, name, url, user_id, client_id, auth_url, token_url, scopes,
    client_secret=None, redis=None, redirect_host="127.0.0.1",
    redirect_port=8765, redirect_path="/mcp/oauth/callback",
    extra_token_params=None, headers=None) -> MCPServerConfig: ...

# parrot/mcp/integration.py:1358 — TO BE REFACTORED
async def add_oauth_mcp_server(
    self, name, url, client_id, auth_url, token_url, scopes,
    user_id, client_secret=None, **kwargs) -> List[str]: ...

# parrot/mcp/registry.py:62 — TO BE EXTENDED
class MCPServerDescriptor(BaseModel):
    name: str              # line 63
    display_name: str      # line 64
    description: str       # line 65
    method_name: str       # line 66
    params: list           # line 67
    category: str          # line 85
    activatable: bool      # line 86
    # auth_type NOT YET PRESENT — to be added
```

### Does NOT Exist
- ~~`MCPServerDescriptor.auth_type`~~ — does not exist yet (being added)
- ~~`create_oauth_mcp_server()` using `MCPOAuth2Config`~~ — current impl uses `OAuthManager`

---

## Implementation Notes

### OAuthManager Removal
Delete lines 282-463 from `parrot/mcp/oauth.py`. Keep everything else:
- `TokenStore` (line 29), `InMemoryTokenStore` (line 35), `RedisTokenStore` (line 49)
- `VaultTokenStore` (line 70)
- `NetSuiteM2MAuth` (line 175)
- Helper functions `_b64url`, `_now`

### Factory Refactoring
```python
def create_oauth_mcp_server(
    *, name, url, user_id, oauth2: MCPOAuth2Config | None = None,
    # Keep old params for backward compat during migration:
    client_id=None, auth_url=None, token_url=None, scopes=None,
    client_secret=None, headers=None, **kwargs
) -> MCPClientConfig:
    if oauth2 is None:
        oauth2 = MCPOAuth2Config(
            client_id=client_id, client_secret=client_secret,
            auth_url=auth_url, token_url=token_url, scopes=scopes or [],
        )
    cfg = MCPClientConfig(name=name, url=url, transport="http",
                          oauth2=oauth2, headers=headers or {})
    return cfg
```

### Key Constraints
- `add_fireflies_mcp_server()` uses API key auth, NOT OAuth2 — it should NOT be changed
- `add_perplexity_mcp_server()` uses API key auth — should NOT be changed
- Keep backward compatibility for `create_oauth_mcp_server()` — accept both old
  positional params and new `MCPOAuth2Config`

---

## Acceptance Criteria

- [ ] `OAuthManager` class fully removed from `parrot/mcp/oauth.py`
- [ ] `TokenStore`, `VaultTokenStore`, `InMemoryTokenStore`, `RedisTokenStore` still intact
- [ ] `NetSuiteM2MAuth` still intact
- [ ] `create_oauth_mcp_server()` works with `MCPOAuth2Config`
- [ ] `create_netsuite_mcp_server()` uses preset + `MCPOAuth2Config`
- [ ] `add_oauth_mcp_server()` works with new config
- [ ] `add_fireflies_mcp_server()` still works (API key, unchanged)
- [ ] `MCPServerDescriptor` has `auth_type` field
- [ ] All tests pass: `pytest tests/mcp/test_oauth_manager_removed.py tests/mcp/test_factory_migration.py -v`

---

## Test Specification

```python
# tests/mcp/test_oauth_manager_removed.py
def test_oauth_manager_not_importable():
    """OAuthManager no longer exists in parrot.mcp.oauth."""
    import parrot.mcp.oauth as mod
    assert not hasattr(mod, 'OAuthManager')

def test_token_stores_still_exist():
    """Token store classes are preserved."""
    from parrot.mcp.oauth import TokenStore, VaultTokenStore, InMemoryTokenStore, RedisTokenStore
    assert all(cls is not None for cls in [TokenStore, VaultTokenStore, InMemoryTokenStore, RedisTokenStore])

def test_netsuite_m2m_still_exists():
    from parrot.mcp.oauth import NetSuiteM2MAuth
    assert NetSuiteM2MAuth is not None


# tests/mcp/test_factory_migration.py
def test_create_oauth_mcp_server_new_config():
    from parrot.mcp.integration import create_oauth_mcp_server
    from parrot.mcp.oauth2_config import MCPOAuth2Config
    cfg = create_oauth_mcp_server(
        name="test", url="http://example.com",
        user_id="user@co.com",
        oauth2=MCPOAuth2Config(client_id="app", scopes=["read"]),
    )
    assert cfg.oauth2 is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — ALL prior tasks (1659-1664) must be completed
3. **Verify the Codebase Contract** — READ `parrot/mcp/oauth.py` and
   `parrot/mcp/integration.py` for current implementations
4. **Search** for all imports of `OAuthManager` across the codebase before deleting
5. **Implement** removal and migration
6. **Run** full test suite to catch any breakage
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-26
**Notes**: Removed OAuthManager class from parrot/mcp/oauth.py (lines 282-463 replaced
with a comment block). Cleaned up oauth.py imports that were only needed by OAuthManager
(os, sys, dataclasses, asyncio, hashlib, secrets, urlencode, aiohttp.web). Refactored
create_oauth_mcp_server() and create_netsuite_mcp_server() in integration.py to use
MCPOAuth2Config. Updated add_oauth_mcp_server() to accept oauth2 param.
Added auth_type: Optional[str] to MCPServerDescriptor in registry.py. All 18 tests pass.

**Deviations from spec**: None. Pre-existing lint issues (ToolPredicate, filter_tools
unused imports; F402 config variable shadow) in integration.py were not fixed as they
are out of scope for this task.
