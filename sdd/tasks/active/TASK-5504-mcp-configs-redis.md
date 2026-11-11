# TASK-5504: Per-user MCP server configs in Redis

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. `MCPPersistenceService` stores catalog-activated MCP servers per `(user_id, agent_id,
server_name)` in DocumentDB `user_mcp_configs` with soft delete. This task adds a `MCP_CONFIGS_STORE`
switch (default `redis`) and a Redis store that preserves soft delete and "`created_at` only on insert".

---

## Scope

- Create `RedisMCPConfigStore` (save / load / remove).
- Dispatch at the top of `save_user_mcp_config`, `load_user_mcp_configs`, `remove_user_mcp_config` when
  `resolve_store_backend("MCP_CONFIGS_STORE") == "redis"`; DocumentDB code unchanged.
- Pin `MCP_CONFIGS_STORE=documentdb` in `test_mcp_persistence.py`; Redis tests.

**NOT in scope**: `AgentTalk._restore_user_mcp_servers` (TASK-5499), `mcp_helper.py` (unchanged — uses the service).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence_redis.py` | CREATE | `RedisMCPConfigStore` |
| `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py` | MODIFY | dispatch in three methods |
| `packages/ai-parrot-server/tests/unit/test_mcp_persistence_redis.py` | CREATE | Redis tests |
| `packages/ai-parrot/tests/unit/test_mcp_persistence.py` | MODIFY | autouse pin `MCP_CONFIGS_STORE=documentdb` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.registry import UserMCPServerConfig                    # verified: packages/ai-parrot/src/parrot/mcp/registry.py:96 (core)
from parrot.userstore import RedisDocumentStore, resolve_store_backend  # TASK-5495/5496
from parrot.userstore.collections import USER_MCP_CONFIGS               # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py
COLLECTION: str = "user_mcp_configs"                                                      # line 31
class MCPPersistenceService:
    async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None:             # line 49 — $set params/vault_credential_name/active/updated_at; $setOnInsert key + created_at
    async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[UserMCPServerConfig]:  # line 94 — active=True only; malformed skipped (warning)
    async def remove_user_mcp_config(self, user_id: str, agent_id: str, server_name: str) -> bool:    # line 136 — soft delete; False when absent

# packages/ai-parrot/src/parrot/mcp/registry.py:96
class UserMCPServerConfig(BaseModel):  # server_name, agent_id, user_id, params: Dict[str, Any], vault_credential_name: Optional[str],
                                       # active: bool = True, created_at: Optional[str] = None, updated_at: Optional[str] = None
```

### Does NOT Exist
- ~~`parrot/mcp/registry.py` in ai-parrot-server~~ — `UserMCPServerConfig` lives in core.
- ~~hard delete of MCP configs~~ — removal is always a soft delete (`active=False`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/mcp_persistence_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_mcp_persistence_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/test_mcp_persistence.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py#MCPPersistenceService",
    "sym:packages/ai-parrot/src/parrot/mcp/registry.py#UserMCPServerConfig"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create `mcp_persistence_redis.py` — *why*: Redis twin with identical semantics.
2. Add `_redis_store()` and a dispatch line in the three methods — *why*: DocumentDB branch stays byte-identical.
3. Pin the legacy test; write Redis tests.

### `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence_redis.py` (CREATE)
```python
"""Per-user MCP server configs in Redis (FEAT-878): ``MCP_CONFIGS_STORE=redis`` (the default)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from parrot.mcp.registry import UserMCPServerConfig
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_MCP_CONFIGS

logger = logging.getLogger(__name__)


class RedisMCPConfigStore:
    """Same semantics as MCPPersistenceService on DocumentDB: soft delete, created_at on insert only."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_MCP_CONFIGS)

    async def save(self, config: UserMCPServerConfig) -> None:
        now = datetime.now(timezone.utc).isoformat()
        key = {"user_id": config.user_id, "agent_id": config.agent_id, "server_name": config.server_name}
        await self._docs.upsert(
            key,
            {"params": config.params, "vault_credential_name": config.vault_credential_name,
             "active": config.active, "updated_at": now},
            on_insert={"created_at": now},
        )

    async def load(self, user_id: str, agent_id: str) -> list[UserMCPServerConfig]:
        """Active configs only; malformed documents skipped with a warning."""
        # FILL IN: find({"user_id": user_id, "agent_id": agent_id, "active": True}); UserMCPServerConfig(**doc)
        #   in try/except → logger.warning("Skipping malformed MCP config doc for user='%s' agent='%s': %s", ...)
        raise NotImplementedError

    async def remove(self, user_id: str, agent_id: str, server_name: str) -> bool:
        """Soft delete; False when absent."""
        now = datetime.now(timezone.utc).isoformat()
        return await self._docs.update(
            {"user_id": user_id, "agent_id": agent_id, "server_name": server_name},
            {"active": False, "updated_at": now},
        )
```
**Why**: `update` never creates, which matches "False when absent"; `active` is filtered in Python by `find`.

### `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'COLLECTION: str = "user_mcp_configs"' .../handlers/mcp_persistence.py)
# AFTER `COLLECTION: str = "user_mcp_configs"` (verified: mcp_persistence.py:31) insert:
_REDIS_STORE = None


def _redis_store():
    """The Redis store when MCP_CONFIGS_STORE resolves to redis, else None (DocumentDB path)."""
    from parrot.userstore import resolve_store_backend  # lazy

    global _REDIS_STORE  # pylint: disable=global-statement
    if resolve_store_backend("MCP_CONFIGS_STORE") != "redis":
        return None
    if _REDIS_STORE is None:
        from .mcp_persistence_redis import RedisMCPConfigStore

        _REDIS_STORE = RedisMCPConfigStore()
    return _REDIS_STORE

# occurrences: 1 each (verified: grep -c on the three `async def` lines at mcp_persistence.py:49, 94, 136)
# FILL IN: first statement after each docstring:
#     store = _redis_store()
#     if store is not None:
#         return await store.save(config)          # load → store.load(user_id, agent_id); remove → store.remove(...)
#   keep the existing logger.info lines for save/remove on the Redis path too (log identities only).
```

### `packages/ai-parrot/tests/unit/test_mcp_persistence.py` (MODIFY)
```python
@pytest.fixture(autouse=True)
def _pin_documentdb(monkeypatch):
    """These tests mock DocumentDB; FEAT-878 made Redis the default."""
    monkeypatch.setenv("MCP_CONFIGS_STORE", "documentdb")
```

### FILL IN checklist
- [ ] `RedisMCPConfigStore.load`
- [ ] three dispatch lines (+ info logs)

---

## Acceptance Criteria

- [ ] `MCP_CONFIGS_STORE` unset → save/load/remove on Redis; remove hides the config; save reactivates it and keeps `created_at`
- [ ] `test_mcp_persistence.py` passes pinned; `test_mcp_helper_handler.py` passes
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_mcp_persistence_redis.py -q`
- `pytest packages/ai-parrot/tests/unit/test_mcp_persistence.py -q`
- `pytest packages/ai-parrot/tests/unit/test_mcp_helper_handler.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_mcp_persistence_redis.py
import pytest

from parrot.handlers import mcp_persistence
from parrot.handlers.mcp_persistence import MCPPersistenceService
from parrot.mcp.registry import UserMCPServerConfig
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def svc(monkeypatch):
    monkeypatch.delenv("MCP_CONFIGS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(mcp_persistence, "_REDIS_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield MCPPersistenceService()


async def test_mcp_configs_redis_soft_delete(svc):
    cfg = UserMCPServerConfig(server_name="perplexity", agent_id="a1", user_id="35", params={"m": 1})
    await svc.save_user_mcp_config(cfg)
    assert len(await svc.load_user_mcp_configs("35", "a1")) == 1
    assert await svc.remove_user_mcp_config("35", "a1", "perplexity") is True
    assert await svc.load_user_mcp_configs("35", "a1") == []
    # FILL IN: save again → active, created_at unchanged


async def test_remove_absent_returns_false(svc): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§3 M8)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5504 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
