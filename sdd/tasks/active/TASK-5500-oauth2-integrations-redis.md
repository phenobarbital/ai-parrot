# TASK-5500: OAuth2 `users_integrations` in Redis

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `AgentTalk` hydrates OAuth toolkits on every call through
`list_users_integrations()` (`handlers/user_objects.py:224`) — the 10 s DocumentDB timeout in the
2026-11-10 log. This task adds `INTEGRATIONS_STORE` dispatch to the four functions of
`parrot.auth.oauth2.persistence`, backed by a Redis store whose documents are
`row.model_dump(mode="json")` (same fields as the DocumentDB documents).

---

## Scope

- Create `RedisUsersIntegrationStore` (upsert / get / delete / list).
- Make each of the four persistence functions dispatch to it when `resolve_store_backend("INTEGRATIONS_STORE") == "redis"`;
  the DocumentDB code stays as it is.
- Pin `INTEGRATIONS_STORE=documentdb` in the existing tests that mock `parrot.auth.oauth2.persistence.DocumentDb`.
- New Redis tests.

**NOT in scope**: OAuth2 token storage (already Redis/Vault), `user_objects.py` (unchanged — it calls `list_users_integrations`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence_redis.py` | CREATE | `RedisUsersIntegrationStore` |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | dispatch in the four functions |
| `packages/ai-parrot/tests/auth/test_integrations_store_redis.py` | CREATE | Redis tests |
| `tests/unit/integrations/oauth2/test_persistence.py` | MODIFY | autouse pin `INTEGRATIONS_STORE=documentdb` |
| `packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py` | MODIFY | pin `INTEGRATIONS_STORE=documentdb` |
| `tests/integration/oauth2/helpers.py` | MODIFY | pin inside the helper's DocumentDb patch context |
| `tests/integration/oauth2/test_e2e_web_connect.py` | MODIFY | pin alongside its DocumentDb patch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.models import UsersIntegrationRow     # verified: auth/oauth2/models.py:172 (persistence.py:19 imports it)
from parrot.userstore import RedisDocumentStore, resolve_store_backend   # TASK-5495/5496
from parrot.userstore.collections import USERS_INTEGRATIONS              # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/persistence.py
USERS_INTEGRATIONS_COLLECTION: str = "users_integrations"                                   # line 27
async def upsert_users_integration(row: UsersIntegrationRow) -> None:                        # line 35 — $set all but key, $setOnInsert key
async def get_users_integration(user_id: str, provider: str) -> Optional[UsersIntegrationRow]:  # line 60
async def delete_users_integration(user_id: str, provider: str) -> None:                     # line 82 — no-op when absent
async def list_users_integrations(user_id: str) -> List[UsersIntegrationRow]:                # line 101 — invalid docs logged + skipped:
    #   logger.warning("Skipping invalid users_integration for user_id=%s", user_id)

# packages/ai-parrot/src/parrot/auth/oauth2/models.py:172
class UsersIntegrationRow(BaseModel):  # user_id: str, provider: str, …, connected_at: datetime,
                                       # updated_at/last_used_at: Optional[datetime], expires_at: Optional[float]
    # has a model_validator(mode="before") mapping legacy "channel" → "channels" (models.py:~221)
```

### Does NOT Exist
- ~~`parrot.auth.oauth2.persistence_redis`~~ — created by this task.
- ~~`UsersIntegrationRow.to_document()`~~ — use `model_dump(mode="json")` / `model_validate(...)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/persistence_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/persistence.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_integrations_store_redis.py", "action": "CREATE"},
    {"path": "tests/unit/integrations/oauth2/test_persistence.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py", "action": "MODIFY"},
    {"path": "tests/integration/oauth2/helpers.py", "action": "MODIFY"},
    {"path": "tests/integration/oauth2/test_e2e_web_connect.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/persistence.py#upsert_users_integration",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/persistence.py#get_users_integration",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/persistence.py#delete_users_integration",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/persistence.py#list_users_integrations",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#UsersIntegrationRow"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `upsert` keeps last-write-wins semantics: `upsert(key, row.model_dump(mode="json", exclude={"user_id", "provider"}), on_insert=key)`.
- Lazy-import `parrot.userstore` inside the dispatch helper (keep the module import graph light).
- Log identities only (user_id, provider), never tokens or emails.

---

## Implementation Blueprint

### Steps (in order)
1. Create `persistence_redis.py` — *why*: Redis twin of the four functions.
2. Add a `_redis_store()` helper and a dispatch line at the top of each function — *why*: DocumentDB code stays untouched (spec §2 dispatch rule).
3. Pin the four existing test modules; write Redis tests.

### `packages/ai-parrot/src/parrot/auth/oauth2/persistence_redis.py` (CREATE)
```python
"""OAuth2 ``users_integrations`` in Redis (FEAT-878). Documents = UsersIntegrationRow.model_dump(mode="json")."""
from __future__ import annotations

import logging

from parrot.auth.oauth2.models import UsersIntegrationRow
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USERS_INTEGRATIONS

logger = logging.getLogger("parrot.auth.oauth2.persistence")


class RedisUsersIntegrationStore:
    """Redis twin of the four ``parrot.auth.oauth2.persistence`` functions."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USERS_INTEGRATIONS)

    async def upsert(self, row: UsersIntegrationRow) -> None:
        key = {"user_id": row.user_id, "provider": row.provider}
        await self._docs.upsert(key, row.model_dump(mode="json", exclude={"user_id", "provider"}), on_insert=key)

    async def get(self, user_id: str, provider: str) -> UsersIntegrationRow | None:
        doc = await self._docs.get({"user_id": user_id, "provider": provider})
        return UsersIntegrationRow.model_validate(doc) if doc else None

    async def delete(self, user_id: str, provider: str) -> None:
        await self._docs.delete({"user_id": user_id, "provider": provider})

    async def list(self, user_id: str) -> list[UsersIntegrationRow]:
        """Invalid documents logged and skipped (same rule as the DocumentDB path)."""
        # FILL IN: find({"user_id": user_id}); model_validate each; on ValueError
        #   logger.warning("Skipping invalid users_integration for user_id=%s", user_id)
        raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'USERS_INTEGRATIONS_COLLECTION: str = "users_integrations"' .../oauth2/persistence.py)
# AFTER `USERS_INTEGRATIONS_COLLECTION: str = "users_integrations"` (verified: persistence.py:27) insert:
_REDIS_STORE = None


def _redis_store():
    """The Redis store when INTEGRATIONS_STORE resolves to redis, else None (DocumentDB path)."""
    from parrot.userstore import resolve_store_backend  # lazy

    global _REDIS_STORE  # pylint: disable=global-statement
    if resolve_store_backend("INTEGRATIONS_STORE") != "redis":
        return None
    if _REDIS_STORE is None:
        from parrot.auth.oauth2.persistence_redis import RedisUsersIntegrationStore

        _REDIS_STORE = RedisUsersIntegrationStore()
    return _REDIS_STORE

# occurrences: 1 each (verified: grep -c on the four `async def` lines at persistence.py:35, 60, 82, 101)
# FILL IN: as the first statement of each function body (after its docstring) add, e.g. for upsert:
#     store = _redis_store()
#     if store is not None:
#         return await store.upsert(row)
#   (get → store.get(user_id, provider); delete → store.delete(...); list → store.list(user_id))
```
**Why**: dispatch-at-the-top keeps the DocumentDB branch byte-identical for `INTEGRATIONS_STORE=documentdb`.

### Existing test modules (MODIFY)
```python
# tests/unit/integrations/oauth2/test_persistence.py and packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py:
@pytest.fixture(autouse=True)
def _pin_documentdb(monkeypatch):
    """These tests mock DocumentDB; FEAT-878 made Redis the default."""
    monkeypatch.setenv("INTEGRATIONS_STORE", "documentdb")
# tests/integration/oauth2/helpers.py (line 16) and test_e2e_web_connect.py (line 54): next to the
#   patch("parrot.auth.oauth2.persistence.DocumentDb", ...) add patch.dict(os.environ, {"INTEGRATIONS_STORE": "documentdb"})
# FILL IN: add `import os` / `from unittest.mock import patch` where missing.
```

### FILL IN checklist
- [ ] `RedisUsersIntegrationStore.list`
- [ ] dispatch line in each of the four functions
- [ ] four test modules pinned

---

## Acceptance Criteria

- [ ] With `INTEGRATIONS_STORE` unset, upsert/get/list/delete go to Redis; an invalid document is skipped
- [ ] With `INTEGRATIONS_STORE=documentdb` the existing tests pass unchanged apart from the pin
- [ ] `datetime` fields round-trip (`connected_at`, `updated_at`)
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/auth/test_integrations_store_redis.py -q`
- `pytest tests/unit/integrations/oauth2/test_persistence.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_agenttalk_oauth_hydration.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_integrations_store_redis.py
from datetime import datetime, timezone

import pytest

from parrot.auth.oauth2 import persistence
from parrot.auth.oauth2.models import UsersIntegrationRow
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_integrations(monkeypatch):
    monkeypatch.delenv("INTEGRATIONS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(persistence, "_REDIS_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield


def _row(**kw):
    base = dict(user_id="35", provider="jira", account_id="a", display_name="A", scopes=["read"],
                connected_at=datetime.now(timezone.utc))
    return UsersIntegrationRow(**{**base, **kw})


async def test_integrations_redis_roundtrip(redis_integrations):
    await persistence.upsert_users_integration(_row())
    assert (await persistence.get_users_integration("35", "jira")).account_id == "a"
    assert len(await persistence.list_users_integrations("35")) == 1
    await persistence.delete_users_integration("35", "jira")
    assert await persistence.get_users_integration("35", "jira") is None


async def test_invalid_document_skipped(redis_integrations): ...  # write a doc missing account_id via RedisDocumentStore
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§3 M5)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5500 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
