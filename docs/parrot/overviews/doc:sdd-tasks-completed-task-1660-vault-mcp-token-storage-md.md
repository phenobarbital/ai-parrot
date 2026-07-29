---
type: Wiki Overview
title: 'TASK-1660: VaultMCPTokenStorage Adapter'
id: doc:sdd-tasks-completed-task-1660-vault-mcp-token-storage-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bridges the MCP SDK's `TokenStorage` protocol with AI-Parrot's `VaultTokenStore`.
relates_to:
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.oauth2_storage
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
---

# TASK-1660: VaultMCPTokenStorage Adapter

**Feature**: FEAT-262 — MCP Server OAuth2 Support
**Spec**: `sdd/specs/mcp-server-oauth2-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1659
**Assigned-to**: unassigned

---

## Context

Bridges the MCP SDK's `TokenStorage` protocol with AI-Parrot's `VaultTokenStore`.
The MCP SDK expects a `TokenStorage` implementation for persisting OAuth2 tokens;
this adapter delegates to the existing vault infrastructure for encrypted persistence.
Implements spec Module 2.

---

## Scope

- Create `parrot/mcp/oauth2_storage.py` with `VaultMCPTokenStorage` class that:
  - Implements MCP SDK's `TokenStorage` protocol (4 methods)
  - `get_tokens()` / `set_tokens()`: delegates to `VaultTokenStore`, converting
    between MCP SDK's `OAuthToken` model and plain `dict`
  - `get_client_info()` / `set_client_info()`: stores `OAuthClientInformationFull`
    in vault using a separate credential name (`mcp_client_{server}_{user}`)
  - Gracefully degrades when vault is unavailable (returns `None`, logs warning)
- Write unit tests with mocked vault

**NOT in scope**: OAuth2 flow logic (TASK-1663), provider registration (TASK-1661),
or transport integration (TASK-1663).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/oauth2_storage.py` | CREATE | VaultMCPTokenStorage adapter |
| `tests/mcp/test_oauth2_storage.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# AI-Parrot vault store (verified: parrot/mcp/oauth.py:70)
from parrot.mcp.oauth import VaultTokenStore  # line 70

# Vault utilities (verified: parrot/mcp/oauth.py:14-18)
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential

# MCP SDK TokenStorage protocol (verified: .venv/.../mcp/client/auth/oauth2.py:72)
from mcp.client.auth.oauth2 import TokenStorage  # Protocol class

# MCP SDK models (verified: .venv/.../mcp/shared/auth.py)
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull
```

### Existing Signatures to Use
```python
# parrot/mcp/oauth.py:29-33
class TokenStore:
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

# parrot/mcp/oauth.py:70
class VaultTokenStore(TokenStore):
    @staticmethod
    def _vault_name(user_id: str, server_name: str) -> str:  # line 88
        return f"mcp_oauth_{server_name}_{user_id}"
    async def get(self, user_id, server_name) -> Optional[Dict]: ...  # line 104
    async def set(self, user_id, server_name, token) -> None: ...     # line 128
    async def delete(self, user_id, server_name) -> None: ...         # line 150

# MCP SDK .venv/.../mcp/client/auth/oauth2.py:72
class TokenStorage(Protocol):
    async def get_tokens(self) -> OAuthToken | None: ...               # line 76
    async def set_tokens(self, tokens: OAuthToken) -> None: ...        # line 80
    async def get_client_info(self) -> OAuthClientInformationFull | None: ...  # line 84
    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None: ...  # line 88

# MCP SDK .venv/.../mcp/shared/auth.py — OAuthToken fields
# OAuthToken(access_token, token_type, expires_in, scope, refresh_token)
```

### Does NOT Exist
- ~~`parrot.mcp.oauth2_storage`~~ — this is the module being created
- ~~`VaultMCPTokenStorage`~~ — does not exist yet
- ~~`VaultTokenStore.get_tokens()`~~ — VaultTokenStore uses `get(user_id, server_name)`, not `get_tokens()`

---

## Implementation Notes

### Pattern to Follow
```python
class VaultMCPTokenStorage:
    """Adapter: MCP SDK TokenStorage → AI-Parrot VaultTokenStore."""

    def __init__(self, user_id: str, server_name: str,
                 vault_store: VaultTokenStore | None = None):
        self._user_id = user_id
        self._server_name = server_name
        self._vault = vault_store or VaultTokenStore()
        self._logger = logging.getLogger(__name__)

    async def get_tokens(self) -> OAuthToken | None:
        data = await self._vault.get(self._user_id, self._server_name)
        if not data:
            return None
        return OAuthToken(**data)  # dict → OAuthToken

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await self._vault.set(self._user_id, self._server_name, tokens.model_dump())
```

### Key Constraints
- `OAuthToken` ↔ `dict` conversion must handle all fields (access_token, token_type, expires_in, scope, refresh_token)
- Client info uses a DIFFERENT vault key: `mcp_client_{server}_{user}` (not `mcp_oauth_`)
- Graceful degradation: vault unavailable → return `None` / log warning, never raise

---

## Acceptance Criteria

- [ ] `VaultMCPTokenStorage` implements all 4 methods of MCP SDK `TokenStorage` protocol
- [ ] `get_tokens()` returns `OAuthToken` from vault data, or `None` if missing
- [ ] `set_tokens()` stores `OAuthToken` as dict in vault
- [ ] `get_client_info()` / `set_client_info()` use separate vault key
- [ ] Graceful degradation when vault unavailable (no exceptions raised)
- [ ] All tests pass: `pytest tests/mcp/test_oauth2_storage.py -v`
- [ ] Import works: `from parrot.mcp.oauth2_storage import VaultMCPTokenStorage`

---

## Test Specification

```python
# tests/mcp/test_oauth2_storage.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull


@pytest.fixture
def storage():
    return VaultMCPTokenStorage(user_id="test@co.com", server_name="test-server")


class TestVaultMCPTokenStorage:
    @pytest.mark.asyncio
    async def test_get_tokens_none(self, storage):
        with patch.object(storage._vault, 'get', new_callable=AsyncMock, return_value=None):
            result = await storage.get_tokens()
            assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_tokens(self, storage):
        token = OAuthToken(access_token="abc", token_type="Bearer")
        with patch.object(storage._vault, 'set', new_callable=AsyncMock) as mock_set:
            await storage.set_tokens(token)
            mock_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_vault_unavailable_graceful(self, storage):
        with patch.object(storage._vault, 'get', new_callable=AsyncMock,
                          side_effect=RuntimeError("vault keys unavailable")):
            result = await storage.get_tokens()
            assert result is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1659 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `VaultTokenStore` at `parrot/mcp/oauth.py:70`
   and MCP SDK `TokenStorage` protocol
4. **Implement** the adapter with proper dict ↔ OAuthToken conversion
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-26
**Notes**: Created `packages/ai-parrot/src/parrot/mcp/oauth2_storage.py` with
VaultMCPTokenStorage implementing all 4 methods of the MCP SDK TokenStorage
protocol. Added field filtering to handle OAuthToken/OAuthClientInformationFull
fields vs. extra fields stored by legacy code. All 17 tests pass.

**Deviations from spec**: Added field filtering (valid_fields check) to prevent
Pydantic validation errors when vault contains extra fields like "expires_at"
or "raw" that are not part of OAuthToken schema.
