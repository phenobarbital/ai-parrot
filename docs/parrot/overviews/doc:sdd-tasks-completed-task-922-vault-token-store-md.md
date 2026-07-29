---
type: Wiki Overview
title: 'TASK-922: Implement VaultTokenStore'
id: doc:sdd-tasks-completed-task-922-vault-token-store-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The NetSuite MCP integration requires encrypted persistence of OAuth2 tokens
relates_to:
- concept: mod:parrot.handlers.vault_utils
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
---

# TASK-922: Implement VaultTokenStore

**Feature**: FEAT-135 — NetSuite MCP Integration
**Spec**: `sdd/specs/netsuite-mcp-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The NetSuite MCP integration requires encrypted persistence of OAuth2 tokens
so that users in production (with a user session) don't have to re-authenticate
on every agent restart. The existing `TokenStore` interface has `InMemoryTokenStore`
and `RedisTokenStore` implementations. This task adds a third: `VaultTokenStore`,
which encrypts tokens using AES-GCM via the existing `vault_utils` helpers.

Implements Spec §3 Module 1 and Spec §2 (token store selection).

---

## Scope

- Implement `VaultTokenStore(TokenStore)` class in `packages/ai-parrot/src/parrot/mcp/oauth.py`
- Must implement `get()`, `set()`, `delete()` methods per the `TokenStore` interface
- Use `store_vault_credential()`, `retrieve_vault_credential()`, `delete_vault_credential()` from `vault_utils`
- Vault credential name format: `mcp_oauth_{server_name}_{user_id}`
- `get()` must return `None` (not raise) when the credential does not exist in the Vault
- Export `VaultTokenStore` from the module

**NOT in scope**: NetSuite factory function, registry entry, tests (separate tasks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/oauth.py` | MODIFY | Add `VaultTokenStore` class after `RedisTokenStore` (after line 598) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import not listed here.

### Verified Imports

```python
from parrot.mcp.oauth import TokenStore, InMemoryTokenStore, RedisTokenStore
    # verified: packages/ai-parrot/src/parrot/mcp/oauth.py:560, :566, :580

from parrot.handlers.vault_utils import (
    store_vault_credential,
    retrieve_vault_credential,
    delete_vault_credential,
)
    # verified: packages/ai-parrot/src/parrot/handlers/vault_utils.py:69, :116, :149
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/oauth.py:560
class TokenStore:
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

# packages/ai-parrot/src/parrot/mcp/oauth.py:580
class RedisTokenStore(TokenStore):
    @staticmethod
    def _key(user_id: str, server_name: str) -> str:
        return f"mcp:oauth:{server_name}:{user_id}"  # line 587

# packages/ai-parrot/src/parrot/handlers/vault_utils.py:69
async def store_vault_credential(
    user_id: str, vault_name: str, secret_params: Dict[str, Any]
) -> None: ...

# packages/ai-parrot/src/parrot/handlers/vault_utils.py:116
async def retrieve_vault_credential(
    user_id: str, vault_name: str
) -> Dict[str, Any]: ...
# Raises KeyError if not found

# packages/ai-parrot/src/parrot/handlers/vault_utils.py:149
async def delete_vault_credential(user_id: str, vault_name: str) -> None: ...
```

### Does NOT Exist

- ~~`parrot.mcp.oauth.VaultTokenStore`~~ — does not exist yet; this task creates it
- ~~`parrot.handlers.vault_utils.has_vault_credential()`~~ — no existence-check helper; `retrieve_vault_credential` raises `KeyError` on miss
- ~~`TokenStore.__init__()`~~ — `TokenStore` has no `__init__`; `InMemoryTokenStore` has one, `RedisTokenStore` takes `redis` param

---

## Implementation Notes

### Pattern to Follow

Follow `RedisTokenStore` (oauth.py:580-598) — same structure, different backend:

```python
class RedisTokenStore(TokenStore):
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def _key(user_id: str, server_name: str) -> str:
        return f"mcp:oauth:{server_name}:{user_id}"

    async def get(self, user_id, server_name):
        raw = await self.redis.get(self._key(user_id, server_name))
        return json.loads(raw) if raw else None

    async def set(self, user_id, server_name, token):
        await self.redis.set(self._key(user_id, server_name), json.dumps(token))

    async def delete(self, user_id, server_name):
        await self.redis.delete(self._key(user_id, server_name))
```

For `VaultTokenStore`:
- `_vault_name()` returns `f"mcp_oauth_{server_name}_{user_id}"` (follows vault naming from vault_utils.py:18)
- `get()` wraps `retrieve_vault_credential()` in try/except `KeyError` → return `None`
- `set()` calls `store_vault_credential()` directly
- `delete()` calls `delete_vault_credential()` directly
- No `__init__` needed (stateless — vault_utils handles DB connection internally)

### Key Constraints

- `get()` must catch `KeyError` from `retrieve_vault_credential` and return `None`
- `get()` must also catch `RuntimeError` (vault keys unavailable) and return `None` with a warning log
- Import `vault_utils` functions at module top level (they are already optional-import-safe via try/except in vault_utils.py)
- Add `import logging` if not already present at top of oauth.py

---

## Acceptance Criteria

- [ ] `VaultTokenStore` class exists in `packages/ai-parrot/src/parrot/mcp/oauth.py`
- [ ] Implements `TokenStore` interface: `get()`, `set()`, `delete()`
- [ ] `get()` returns `None` when credential not found (does not raise)
- [ ] `get()` returns `None` when vault keys unavailable (does not raise)
- [ ] Vault credential name follows `mcp_oauth_{server_name}_{user_id}` pattern
- [ ] Import works: `from parrot.mcp.oauth import VaultTokenStore`

---

## Test Specification

```python
# tests/mcp/test_netsuite_mcp.py (partial — VaultTokenStore tests)
import pytest
from unittest.mock import AsyncMock, patch

from parrot.mcp.oauth import VaultTokenStore


@pytest.fixture
def vault_store():
    return VaultTokenStore()


@pytest.fixture
def sample_token():
    return {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_at": 9999999999,
        "token_type": "Bearer",
    }


class TestVaultTokenStore:
    @pytest.mark.asyncio
    async def test_set_stores_credential(self, vault_store, sample_token):
        with patch("parrot.mcp.oauth.store_vault_credential", new_callable=AsyncMock) as mock_store:
            await vault_store.set("user1", "netsuite", sample_token)
            mock_store.assert_called_once_with(
                "user1", "mcp_oauth_netsuite_user1", sample_token
            )

    @pytest.mark.asyncio
    async def test_get_retrieves_credential(self, vault_store, sample_token):
        with patch("parrot.mcp.oauth.retrieve_vault_credential", new_callable=AsyncMock, return_value=sample_token):
            result = await vault_store.get("user1", "netsuite")
            assert result == sample_token

    @pytest.mark.asyncio
    async def test_get_returns_none_on_missing(self, vault_store):
        with patch("parrot.mcp.oauth.retrieve_vault_credential", new_callable=AsyncMock, side_effect=KeyError("not found")):
            result = await vault_store.get("user1", "netsuite")
            assert result is None

    @pytest.mark.asyncio
    async def test_delete_removes_credential(self, vault_store):
        with patch("parrot.mcp.oauth.delete_vault_credential", new_callable=AsyncMock) as mock_del:
            await vault_store.delete("user1", "netsuite")
            mock_del.assert_called_once_with("user1", "mcp_oauth_netsuite_user1")

    def test_vault_name_format(self, vault_store):
        name = vault_store._vault_name("netsuite", "user@co.com")
        assert name == "mcp_oauth_netsuite_user@co.com"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/netsuite-mcp-integration.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm imports and signatures still match
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the `VaultTokenStore` class in oauth.py after `RedisTokenStore`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-922-vault-token-store.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-04-29
**Notes**: VaultTokenStore implemented in oauth.py after RedisTokenStore. Added import logging and vault_utils imports at module top. All methods implemented per spec.

**Deviations from spec**: none
