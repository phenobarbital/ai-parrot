---
type: Wiki Overview
title: 'TASK-923: NetSuite MCP Factory & Mixin Helper'
id: doc:sdd-tasks-completed-task-923-netsuite-factory-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core task of FEAT-135. It adds the `create_netsuite_mcp_server()`
  factory
relates_to:
- concept: mod:parrot.mcp.integration
  rel: mentions
---

# TASK-923: NetSuite MCP Factory & Mixin Helper

**Feature**: FEAT-135 — NetSuite MCP Integration
**Spec**: `sdd/specs/netsuite-mcp-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-922
**Assigned-to**: unassigned

---

## Context

This is the core task of FEAT-135. It adds the `create_netsuite_mcp_server()` factory
function that constructs NetSuite-specific URLs from `account_id` and delegates to
the existing `create_oauth_mcp_server()` pipeline, plus the `add_netsuite_mcp_server()`
convenience method on `MCPEnabledMixin`.

Implements Spec §3 Module 2 and Spec §2 (New Public Interfaces).

---

## Scope

- Add NetSuite URL template constants at module level in `integration.py`
- Implement `create_netsuite_mcp_server()` factory function in `integration.py`
- Implement `add_netsuite_mcp_server()` method on `MCPEnabledMixin` in `integration.py`
- Factory must accept `token_store` parameter; default to `InMemoryTokenStore` when not provided
- Factory must delegate to `create_oauth_mcp_server()` after constructing URLs
- Scope must be hardcoded to `["mcp"]`

**NOT in scope**: VaultTokenStore implementation (TASK-922), registry entry (TASK-924), tests (TASK-925)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | Add URL constants, `create_netsuite_mcp_server()` factory, and `add_netsuite_mcp_server()` mixin method |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.

### Verified Imports

```python
# Already imported at top of integration.py:
from .oauth import OAuthManager, InMemoryTokenStore, RedisTokenStore
    # verified: integration.py:11-14

from .client import MCPClientConfig as MCPServerConfig, MCPConnectionError
    # verified: integration.py:16-18
    # NOTE: MCPServerConfig IS MCPClientConfig aliased. Use MCPServerConfig inside this file.
```

```python
# NEW import needed for VaultTokenStore (after TASK-922 is done):
from .oauth import VaultTokenStore
    # will exist at: packages/ai-parrot/src/parrot/mcp/oauth.py (after TASK-922)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/integration.py:690
def create_oauth_mcp_server(
    *, name: str, url: str, user_id: str, client_id: str,
    auth_url: str, token_url: str, scopes: list[str],
    client_secret: str | None = None, redis=None,
    redirect_host: str = "127.0.0.1", redirect_port: int = 8765,
    redirect_path: str = "/mcp/oauth/callback",
    extra_token_params: dict | None = None,
    headers: dict | None = None,
) -> MCPServerConfig: ...
# NOTE: This function creates its own token_store internally (Redis or InMemory based on `redis` param).
# For NetSuite, we need to pass a custom token_store. The factory uses OAuthManager directly
# (see lines 708-721) to allow VaultTokenStore injection.

# packages/ai-parrot/src/parrot/mcp/oauth.py:605
class OAuthManager:
    def __init__(self, *, user_id: str, server_name: str, client_id: str,
                 auth_url: str, token_url: str, scopes: list[str],
                 redirect_host: str = "127.0.0.1", redirect_port: int = 8765,
                 redirect_path: str = "/mcp/oauth/callback",
                 token_store: TokenStore, client_secret: str | None = None,
                 extra_token_params: dict | None = None,
                 http_timeout: float = 15.0): ...
    def token_supplier(self) -> Optional[str]: ...   # line 648
    async def ensure_token(self) -> str: ...          # line 658

# packages/ai-parrot/src/parrot/mcp/integration.py:1087
class MCPEnabledMixin:
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]: ...  # line 1094

# Pattern — add_perplexity_mcp_server (integration.py:1161-1169):
    async def add_perplexity_mcp_server(
        self,
        api_key: str,
        name: str = "perplexity",
        **kwargs
    ) -> List[str]:
        config = create_perplexity_mcp_server(api_key, name=name, **kwargs)
        return await self.add_mcp_server(config)
```

### Does NOT Exist

- ~~`create_oauth_mcp_server(token_store=...)`~~ — `create_oauth_mcp_server` does NOT accept a `token_store` parameter; it creates one internally from `redis` param. The NetSuite factory must wire `OAuthManager` directly (copy the pattern from lines 708-741 of integration.py).
- ~~`parrot.mcp.integration.create_netsuite_mcp_server`~~ — does not exist yet; this task creates it
- ~~`MCPEnabledMixin.add_netsuite_mcp_server`~~ — does not exist yet; this task creates it
- ~~`MCPServerConfig` as a standalone class~~ — it is `MCPClientConfig` aliased at line 17

---

## Implementation Notes

### Pattern to Follow

The NetSuite factory CANNOT simply delegate to `create_oauth_mcp_server()` because
that function doesn't accept a `token_store` parameter — it creates its own from
the `redis` param. Instead, follow the internal pattern of `create_oauth_mcp_server()`
(lines 690-742) but with custom token store selection:

```python
# URL templates
NETSUITE_MCP_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools"
NETSUITE_AUTH_URL = "https://{account_id}.app.netsuite.com/app/login/oauth2/authorize.nl"
NETSUITE_TOKEN_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token"
NETSUITE_SCOPES = ["mcp"]

def create_netsuite_mcp_server(
    *,
    account_id: str,
    client_id: str,
    user_id: str,
    token_store: "TokenStore | None" = None,
    redirect_host: str = "127.0.0.1",
    redirect_port: int = 8765,
    redirect_path: str = "/mcp/oauth/callback",
    headers: dict | None = None,
) -> MCPServerConfig:
    url = NETSUITE_MCP_URL.format(account_id=account_id)
    auth_url = NETSUITE_AUTH_URL.format(account_id=account_id)
    token_url = NETSUITE_TOKEN_URL.format(account_id=account_id)

    if token_store is None:
        token_store = InMemoryTokenStore()

    oauth = OAuthManager(
        user_id=user_id,
        server_name="netsuite",
        client_id=client_id,
        auth_url=auth_url,
        token_url=token_url,
        scopes=NETSUITE_SCOPES,
        redirect_host=redirect_host,
        redirect_port=redirect_port,
        redirect_path=redirect_path,
        token_store=token_store,
    )

    cfg = MCPServerConfig(
        name="netsuite",
        transport="http",
        url=url,
        headers=headers or {"Content-Type": "application/json"},
        auth_type="oauth",
        auth_config={
            "auth_url": auth_url,
            "token_url": token_url,
            "scopes": NETSUITE_SCOPES,
            "client_id": client_id,
            "redirect_uri": oauth.redirect_uri,
        },
        token_supplier=oauth.token_supplier,
    )
    cfg._ensure_oauth_token = oauth.ensure_token
    return cfg
```

For the mixin helper:

```python
async def add_netsuite_mcp_server(
    self,
    account_id: str,
    client_id: str,
    user_id: str,
    **kwargs,
) -> List[str]:
    config = create_netsuite_mcp_server(
        account_id=account_id,
        client_id=client_id,
        user_id=user_id,
        **kwargs,
    )
    return await self.add_mcp_server(config)
```

### Key Constraints

- Place URL constants near other factory functions (after line 742 or at module top)
- Place `create_netsuite_mcp_server()` after `create_oauth_mcp_server()` (after line 742)
- Place `add_netsuite_mcp_server()` on `MCPEnabledMixin` after `add_fireflies_mcp_server()` (after line 1191)
- Add `VaultTokenStore` to the import from `.oauth` (line 11-14)

---

## Acceptance Criteria

- [ ] `create_netsuite_mcp_server()` exists and returns valid `MCPServerConfig` (aliased `MCPClientConfig`)
- [ ] URLs are correctly templated from `account_id`
- [ ] Scope is hardcoded to `["mcp"]`
- [ ] Default `token_store` is `InMemoryTokenStore` when `None` provided
- [ ] `VaultTokenStore` can be passed as `token_store` parameter
- [ ] `add_netsuite_mcp_server()` exists on `MCPEnabledMixin`
- [ ] `cfg._ensure_oauth_token` is attached for token lifecycle management
- [ ] `token_supplier` is set on the returned config

---

## Test Specification

```python
# tests/mcp/test_netsuite_mcp.py (partial — factory tests)
import pytest
from parrot.mcp.integration import create_netsuite_mcp_server


class TestCreateNetsuiteMcpServer:
    def test_url_construction(self):
        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
        )
        assert cfg.url == "https://4984231.suitetalk.api.netsuite.com/services/mcp/v1/suiteapp/com.netsuite.mcpstandardtools"

    def test_scopes_are_mcp_only(self):
        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
        )
        assert cfg.auth_config["scopes"] == ["mcp"]

    def test_default_token_store_is_in_memory(self):
        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
        )
        assert cfg.token_supplier is not None

    def test_token_supplier_is_callable(self):
        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
        )
        assert callable(cfg.token_supplier)

    def test_ensure_token_attached(self):
        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
        )
        assert hasattr(cfg, "_ensure_oauth_token")
        assert callable(cfg._ensure_oauth_token)

    def test_transport_is_http(self):
        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
        )
        assert cfg.transport == "http"

    def test_name_is_netsuite(self):
        cfg = create_netsuite_mcp_server(
            account_id="4984231",
            client_id="test-client",
            user_id="user@co.com",
        )
        assert cfg.name == "netsuite"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/netsuite-mcp-integration.spec.md` for full context
2. **Check dependencies** — verify TASK-922 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `create_oauth_mcp_server` signature and `MCPEnabledMixin` location
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the factory function and mixin helper in integration.py
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-923-netsuite-factory-helper.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-04-29
**Notes**: Added VaultTokenStore to import in integration.py. Added NETSUITE_MCP_URL, NETSUITE_AUTH_URL, NETSUITE_TOKEN_URL constants and NETSUITE_SCOPES=["mcp"]. Implemented create_netsuite_mcp_server() factory and add_netsuite_mcp_server() mixin method after add_alphavantage_mcp_server(). _ensure_oauth_token and token_supplier both wired correctly.

**Deviations from spec**: none
