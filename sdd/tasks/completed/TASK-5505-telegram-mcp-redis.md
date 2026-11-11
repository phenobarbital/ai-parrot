# TASK-5505: Telegram `/add_mcp` configs in Redis and the persistence gate

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §2 "Telegram gate", §3 Module 9. `TelegramMCPPersistenceService` persists the non-secret half of
`/add_mcp` servers in DocumentDB `telegram_user_mcp_configs`, and only when `USE_DOCUMENTDB` is true (opt-in,
so a DocumentDB-less deployment never blocks a Telegram login). FEAT-878 adds `TELEGRAM_MCP_STORE`: with
`redis` (the default) persistence is always on; with `documentdb` today's `USE_DOCUMENTDB` opt-in applies.

---

## Scope

- Create `RedisTelegramMCPStore` (save / list / read_one / remove) with the DocumentDB document shape
  `{user_id, name, params, vault_credential_name, active, created_at, updated_at}`.
- Add `persistence_enabled()`; keep `documentdb_enabled()` as an alias returning `persistence_enabled()`.
- Dispatch the four service methods to Redis when the switch resolves `redis`; DocumentDB path unchanged.
- Switch the four `documentdb_enabled` uses in `mcp_commands.py` to `persistence_enabled`.
- Pin `TELEGRAM_MCP_STORE=documentdb` in the two existing test modules; Redis tests.

**NOT in scope**: vault secrets of `/add_mcp` (they already go through `vault_utils` → TASK-5497), `wrapper.py` docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence_redis.py` | CREATE | `RedisTelegramMCPStore` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py` | MODIFY | `persistence_enabled`, alias, dispatch |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py` | MODIFY | use `persistence_enabled` |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_persistence_redis.py` | CREATE | Redis + gate tests |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_documentdb_gate.py` | MODIFY | autouse pin `TELEGRAM_MCP_STORE=documentdb` |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py` | MODIFY | autouse pin `TELEGRAM_MCP_STORE=documentdb` |
| `packages/ai-parrot-server/tests/unit/test_credentials_store_dispatch.py` | MODIFY | shared wave fix (see TASK-5498) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot import conf as parrot_conf                                   # verified: mcp_persistence.py:37 (USE_DOCUMENTDB read via getattr)
from parrot.userstore import RedisDocumentStore, resolve_store_backend   # TASK-5495/5496
from parrot.userstore.collections import TELEGRAM_USER_MCP_CONFIGS       # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py
def documentdb_enabled() -> bool:                                         # line 44 — bool(getattr(parrot_conf, "USE_DOCUMENTDB", False))
async def _documentdb() -> AsyncIterator[Optional[DocumentDb]]:           # line 57 — yields None when disabled
class TelegramMCPPublicParams(BaseModel):                                 # line 76
class UserTelegramMCPConfig(BaseModel):                                   # line 106 — user_id, name, params: TelegramMCPPublicParams,
                                                                          #   vault_credential_name, active=True, created_at: datetime, updated_at: datetime
class TelegramMCPPersistenceService:                                      # line 134
    COLLECTION: str = "telegram_user_mcp_configs"                         # line 153
    async def save(self, user_id: str, name: str, params: TelegramMCPPublicParams,
                   vault_credential_name: Optional[str]) -> None:         # line 155 — $set params.model_dump()/vault/active=True/updated_at; $setOnInsert key+created_at (ISO strings)
    async def list(self, user_id: str) -> List[UserTelegramMCPConfig]:    # line 204 — active only; malformed skipped
    async def read_one(self, user_id: str, name: str) -> Optional[UserTelegramMCPConfig]:  # line 241
    async def remove(self, user_id: str, name: str) -> tuple[bool, Optional[str]]:        # line 279 — soft delete; returns (found, vault_credential_name)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py
#   `documentdb_enabled` occurs 4×: import (line 53), line 262 `if tool_manager is None or not documentdb_enabled():`,
#   line 383 `persist = documentdb_enabled()`, line 449 `if not documentdb_enabled():`
```

### Does NOT Exist
- ~~`persistence_enabled`, `RedisTelegramMCPStore`~~ — created by this task.
- ~~`TelegramMCPPersistenceService.delete`~~ — removal is `remove()` (soft delete).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_persistence_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_documentdb_gate.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py#documentdb_enabled",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py#TelegramMCPPersistenceService",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py#UserTelegramMCPConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py#TelegramMCPPublicParams"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Gate: `persistence_enabled()` = `True` when `TELEGRAM_MCP_STORE` resolves `redis`; when it resolves
  `documentdb`, `bool(getattr(parrot_conf, "USE_DOCUMENTDB", False))` (unchanged rule). Read at call time.
- A misconfigured switch makes `persistence_enabled()` return `False` and log a warning — a Telegram login
  must never fail because of storage configuration (module docstring rationale).
- Parse `params` back into `TelegramMCPPublicParams` on read, as the DocumentDB `list()` does.

---

## Implementation Blueprint

### Steps (in order)
1. Create `mcp_persistence_redis.py` — *why*: Redis twin with the same document shape.
2. Add `persistence_enabled()`, make `documentdb_enabled()` an alias, dispatch the four methods — *why*: spec §2 gate.
3. Update `mcp_commands.py` (4 uses) — *why*: callers must use the backend-neutral gate.
4. Pin the two legacy test modules; write Redis tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence_redis.py` (CREATE)
```python
"""Telegram /add_mcp configs in Redis (FEAT-878): ``TELEGRAM_MCP_STORE=redis`` (the default)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import TELEGRAM_USER_MCP_CONFIGS

from .mcp_persistence import TelegramMCPPublicParams, UserTelegramMCPConfig

logger = logging.getLogger(__name__)


class RedisTelegramMCPStore:
    """Same semantics as TelegramMCPPersistenceService on DocumentDB: soft delete, created_at on insert only."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(TELEGRAM_USER_MCP_CONFIGS)

    async def save(self, user_id: str, name: str, params: TelegramMCPPublicParams,
                   vault_credential_name: Optional[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._docs.upsert(
            {"user_id": user_id, "name": name},
            {"params": params.model_dump(), "vault_credential_name": vault_credential_name,
             "active": True, "updated_at": now},
            on_insert={"created_at": now},
        )

    async def list(self, user_id: str) -> List[UserTelegramMCPConfig]:
        # FILL IN: find({"user_id": user_id, "active": True}); parse like the DocumentDB list() (params → TelegramMCPPublicParams);
        #   skip malformed with logger.warning("Skipping malformed Telegram MCP config doc for user=%r: %s", user_id, exc)
        raise NotImplementedError

    async def read_one(self, user_id: str, name: str) -> Optional[UserTelegramMCPConfig]:
        # FILL IN: mirror TelegramMCPPersistenceService.read_one (line 241) semantics on self._docs.get(...)
        raise NotImplementedError

    async def remove(self, user_id: str, name: str) -> tuple[bool, Optional[str]]:
        """Soft delete; returns (found, vault_credential_name)."""
        existing = await self._docs.get({"user_id": user_id, "name": name})
        if existing is None:
            return False, None
        await self._docs.update({"user_id": user_id, "name": name},
                                {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()})
        return True, existing.get("vault_credential_name")
```

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def documentdb_enabled() -> bool:' .../telegram/mcp_persistence.py)
# REPLACE `def documentdb_enabled() -> bool:` (line 44) and its body with:
def persistence_enabled() -> bool:
    """True when TELEGRAM_MCP_STORE resolves redis, or resolves documentdb and USE_DOCUMENTDB is true."""
    # FILL IN: lazy `from parrot.userstore import resolve_store_backend`; on any exception log a warning
    #   (type name only) and return False — bounded by spec §2 Telegram gate / AC9.
    raise NotImplementedError


def documentdb_enabled() -> bool:
    """Deprecated alias of :func:`persistence_enabled` (kept for importers)."""
    return persistence_enabled()


def _redis_store():
    """RedisTelegramMCPStore when the switch resolves redis, else None."""
    # FILL IN: same lazy-singleton pattern as other FEAT-878 dispatchers (module global _REDIS_STORE).
    raise NotImplementedError
# NOTE: _documentdb() (line 57) keeps calling the DocumentDB gate: make it check
#   `bool(getattr(parrot_conf, "USE_DOCUMENTDB", False))` directly instead of documentdb_enabled(),
#   so the documentdb path is unchanged.

# occurrences: 1 (verified: grep -c 'class TelegramMCPPersistenceService:' .../telegram/mcp_persistence.py)
# FILL IN: in save (155), list (204), read_one (241), remove (279), as the first statement after the docstring:
#     store = _redis_store()
#     if store is not None:
#         return await store.<op>(...)
```

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py` (MODIFY)
```python
# occurrences: 4 (verified: grep -c 'documentdb_enabled' .../telegram/mcp_commands.py) — replace each:
#   line 53 import `documentdb_enabled,` → `persistence_enabled,`
#   line 262 `not documentdb_enabled()` → `not persistence_enabled()`
#   line 383 `persist = documentdb_enabled()` → `persist = persistence_enabled()`
#   line 449 `if not documentdb_enabled():` → `if not persistence_enabled():`
# FILL IN: update the module docstring sentence at line ~31 ("Persistence is opt-in via USE_DOCUMENTDB") to describe the new gate.
```

### Legacy test modules (MODIFY)
```python
@pytest.fixture(autouse=True)
def _pin_documentdb(monkeypatch):
    """These tests exercise the USE_DOCUMENTDB opt-in; FEAT-878 made Redis the default."""
    monkeypatch.setenv("TELEGRAM_MCP_STORE", "documentdb")
# Add to test_mcp_documentdb_gate.py and test_mcp_commands.py. If test_mcp_commands patches
#   `...mcp_commands.documentdb_enabled`, change the target to `...mcp_commands.persistence_enabled`.
```

### FILL IN checklist
- [ ] `persistence_enabled` + `_redis_store`
- [ ] `RedisTelegramMCPStore.list` / `read_one`
- [ ] four dispatch lines; `_documentdb()` reads USE_DOCUMENTDB directly
- [ ] mcp_commands uses + docstring

---

## Acceptance Criteria

- [ ] `TELEGRAM_MCP_STORE` unset → `/add_mcp` persists in Redis even with `USE_DOCUMENTDB=false` (AC9)
- [ ] `TELEGRAM_MCP_STORE=documentdb` → behaviour identical to today (existing tests pass pinned)
- [ ] Invalid switch → `persistence_enabled()` is False, no exception
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_persistence_redis.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_documentdb_gate.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_persistence_redis.py
import pytest

from parrot.integrations.telegram import mcp_persistence
from parrot.integrations.telegram.mcp_persistence import (
    TelegramMCPPersistenceService, TelegramMCPPublicParams, persistence_enabled,
)
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def svc(monkeypatch):
    monkeypatch.delenv("TELEGRAM_MCP_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr("parrot.conf.USE_DOCUMENTDB", False, raising=False)
    monkeypatch.setattr(mcp_persistence, "_REDIS_STORE", None, raising=False)
    async with redis_test_settings(monkeypatch):
        yield TelegramMCPPersistenceService()


def test_telegram_gate(monkeypatch): ...  # unset → True; documentdb + USE_DOCUMENTDB False → False; bogus → False


async def test_telegram_redis_roundtrip(svc):
    params = TelegramMCPPublicParams(name="srv", url="https://example.test/mcp")
    await svc.save("tg:1", "srv", params, "tg_mcp_srv")
    assert [c.name for c in await svc.list("tg:1")] == ["srv"]
    assert await svc.remove("tg:1", "srv") == (True, "tg_mcp_srv")
    assert await svc.list("tg:1") == []
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Telegram gate, §3 M9)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5505 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note


- Task: TASK-5505
- Feature: redis-user-stores
- Implementation SHA: 3b6790806012f759699020949e27c5bf17ef4178
- Closed at (UTC): 2026-11-11T02:01:33+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 199s · Tokens: n/a |
