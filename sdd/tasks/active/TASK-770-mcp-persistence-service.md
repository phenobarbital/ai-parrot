# TASK-770: MCP Persistence Service — DocumentDB Storage for User MCP Configs

**Feature**: FEAT-110 — MCP Mixin Helper Handler
**Spec**: `sdd/specs/mcp-mixin-helper-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-769
**Assigned-to**: unassigned

---

## Context

This task implements the persistence layer that saves and loads per-user, per-agent
MCP server configurations to/from DocumentDB. It enables the restore-on-session-init
flow (TASK-772) and is called by the HTTP handler (TASK-771) on activate/deactivate.

Implements spec Section 3, Module 2.

---

## Scope

- Implement `MCPPersistenceService` class in `parrot/handlers/mcp_persistence.py` with:
  - `save_user_mcp_config(config: UserMCPServerConfig) -> None` — upsert to DocumentDB
  - `load_user_mcp_configs(user_id: str, agent_id: str) -> List[UserMCPServerConfig]` — load all active configs
  - `remove_user_mcp_config(user_id: str, agent_id: str, server_name: str) -> bool` — delete one config
- Use the `DocumentDb` async context manager for all DB operations.
- Use the `user_mcp_configs` collection name.
- Store Vault credential references (name only, never the secret value).
- Write unit tests with mocked DocumentDB.

**NOT in scope**: Vault credential storage/retrieval (handled by TASK-771), HTTP handler, session restore.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/mcp_persistence.py` | CREATE | MCPPersistenceService class |
| `tests/unit/test_mcp_persistence.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.documentdb import DocumentDb  # verified: parrot/interfaces/documentdb.py
from parrot.mcp.registry import UserMCPServerConfig  # created by TASK-769
from navconfig.logging import logging  # verified: used throughout handlers
```

### Existing Signatures to Use
```python
# parrot/interfaces/documentdb.py — DocumentDb async context manager
class DocumentDb:
    async def __aenter__(self) -> 'DocumentDb': ...
    async def __aexit__(self, *args) -> None: ...
    async def read_one(self, collection: str, filter: dict) -> Optional[dict]: ...
    async def read_many(self, collection: str, filter: dict) -> list: ...
    async def insert_one(self, collection: str, document: dict) -> ...: ...
    async def update_one(self, collection: str, filter: dict, update: dict) -> ...: ...
    async def delete_one(self, collection: str, filter: dict) -> ...: ...

# parrot/mcp/registry.py (created by TASK-769)
class UserMCPServerConfig(BaseModel):
    server_name: str
    agent_id: str
    user_id: str
    params: Dict[str, Any]  # non-secret params only
    vault_credential_name: Optional[str] = None
    active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

# parrot/handlers/credentials.py — pattern reference for DocumentDb usage
class CredentialsHandler(BaseView):  # line 71
    COLLECTION: str = "user_credentials"  # line 83
    # Usage pattern (line 191):
    # async with DocumentDb() as db:
    #     doc = await db.read_one(self.COLLECTION, {"user_id": user_id, "name": name})
```

### Does NOT Exist
- ~~`parrot.handlers.mcp_persistence`~~ — does not exist yet; this task creates it
- ~~`MCPPersistenceService`~~ — does not exist; this task creates it
- ~~`user_mcp_configs` DocumentDB collection~~ — does not exist yet; created implicitly on first write
- ~~`DocumentDb.upsert_one()`~~ — no upsert method; use `read_one` + `update_one`/`insert_one`
- ~~`DocumentDb.find()`~~ — use `read_many`, not `find`

---

## Implementation Notes

### Pattern to Follow
Follow `CredentialsHandler` (`credentials.py:164-200`) for DocumentDb usage patterns:

```python
async with DocumentDb() as db:
    doc = await db.read_one(
        COLLECTION,
        {"user_id": user_id, "server_name": server_name, "agent_id": agent_id}
    )
```

### Key Constraints
- Collection name: `"user_mcp_configs"`
- Documents are scoped by compound key: `(user_id, agent_id, server_name)`
- `save_user_mcp_config` must be an upsert: if a doc with the same compound key exists, update it; otherwise insert
- `created_at` set on first insert, `updated_at` set on every save (use ISO-8601 format)
- `load_user_mcp_configs` must filter by `active: True` — deactivated configs stay in DB but are not restored
- `remove_user_mcp_config` should set `active: False` (soft delete) rather than hard-deleting, so configs can be re-activated later. Return `True` if a doc was found and updated, `False` otherwise.
- The `params` dict MUST NOT contain secret values — only non-secret config params. The `vault_credential_name` field points to where secrets are stored.

### References in Codebase
- `parrot/handlers/credentials.py:164-200` — DocumentDb async context manager usage
- `parrot/handlers/credentials.py:83` — COLLECTION constant pattern

---

## Acceptance Criteria

- [ ] `save_user_mcp_config` creates a new document in DocumentDB
- [ ] `save_user_mcp_config` updates existing document on second call with same key
- [ ] `load_user_mcp_configs` returns only active configs for the given user/agent
- [ ] `remove_user_mcp_config` soft-deletes (sets `active: False`), returns `True`
- [ ] `remove_user_mcp_config` returns `False` for nonexistent config
- [ ] No secret values stored in the `params` dict
- [ ] All tests pass: `pytest tests/unit/test_mcp_persistence.py -v`
- [ ] Import works: `from parrot.handlers.mcp_persistence import MCPPersistenceService`

---

## Test Specification

```python
# tests/unit/test_mcp_persistence.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.handlers.mcp_persistence import MCPPersistenceService
from parrot.mcp.registry import UserMCPServerConfig


@pytest.fixture
def service():
    return MCPPersistenceService()


@pytest.fixture
def sample_config():
    return UserMCPServerConfig(
        server_name="perplexity",
        agent_id="test-agent",
        user_id="user-123",
        params={},
        vault_credential_name="mcp_perplexity_test-agent",
        active=True,
    )


class TestMCPPersistenceService:
    @pytest.mark.asyncio
    async def test_save_new_config(self, service, sample_config):
        """First save creates a new document."""
        with patch("parrot.handlers.mcp_persistence.DocumentDb") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.read_one.return_value = None
            mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await service.save_user_mcp_config(sample_config)
            mock_db.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, service, sample_config):
        """Second save updates existing document."""
        with patch("parrot.handlers.mcp_persistence.DocumentDb") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.read_one.return_value = {"_id": "existing"}
            mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await service.save_user_mcp_config(sample_config)
            mock_db.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_returns_active_only(self, service):
        """Load filters by active=True."""
        with patch("parrot.handlers.mcp_persistence.DocumentDb") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.read_many.return_value = [
                {"server_name": "perplexity", "agent_id": "a", "user_id": "u",
                 "params": {}, "active": True}
            ]
            mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            configs = await service.load_user_mcp_configs("u", "a")
            assert len(configs) == 1

    @pytest.mark.asyncio
    async def test_remove_soft_deletes(self, service):
        """Remove sets active=False, returns True."""
        with patch("parrot.handlers.mcp_persistence.DocumentDb") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.read_one.return_value = {"_id": "existing", "active": True}
            mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await service.remove_user_mcp_config("u", "a", "perplexity")
            assert result is True

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self, service):
        """Remove returns False if config not found."""
        with patch("parrot.handlers.mcp_persistence.DocumentDb") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.read_one.return_value = None
            mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await service.remove_user_mcp_config("u", "a", "nonexistent")
            assert result is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-769 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `DocumentDb` methods and `UserMCPServerConfig` model
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-770-mcp-persistence-service.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
