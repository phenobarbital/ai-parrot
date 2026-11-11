# TASK-5503: Per-user toolkit overrides in Redis

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. `AgentTalk` loads toolkit overrides on every call (`ToolkitConfigService.load`,
`agent.py:1085`) — the "Toolkit override application failed … ConnectionError" warning in the 2026-11-10
log. `ToolkitConfigService` already prefers a registered Postgres store (`_PG_OVERRIDES`, FEAT-621). This
task adds a Redis store and an `_active_override_store()` dispatch so `TOOLKIT_OVERRIDES_STORE=redis`
(the default) never touches DocumentDB.

---

## Scope

- Create `RedisToolkitOverrideStore` (save / load / remove / purge_agent / revision) over `USER_TOOLKIT_CONFIGS`;
  documents are `UserToolkitOverride.model_dump(mode="json")`.
- Add `_active_override_store()` to `toolkit_persistence.py` and use it in the five methods instead of `_PG_OVERRIDES`.
- Tests on Redis; confirm existing override tests still pass.

**NOT in scope**: the Postgres store (unchanged), `agent.py` (unchanged — it calls `ToolkitConfigService`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence_redis.py` | CREATE | `RedisToolkitOverrideStore` |
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` | MODIFY | `_active_override_store()` dispatch |
| `packages/ai-parrot-server/tests/unit/test_toolkit_overrides_redis.py` | CREATE | Redis tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.toolkit_persistence import UserToolkitOverride   # verified: toolkit_persistence.py:17
from parrot.userstore import RedisDocumentStore, resolve_store_backend   # TASK-5495/5496
from parrot.userstore.collections import USER_TOOLKIT_CONFIGS            # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py
COLLECTION: str = "user_toolkit_configs"                       # line 14
class UserToolkitOverride(BaseModel):                          # line 17 — user_id, agent_id, slug, params: dict, secret_refs: dict[str, str], updated_at: str (ISO)
_PG_OVERRIDES: Any = None                                      # line 29
def set_toolkit_override_store(store: Any) -> None:            # line 32 — Studio registers Postgres; None restores DocumentDB
class ToolkitConfigService:                                    # line 38
    async def save(self, override: UserToolkitOverride) -> None:                       # PG check line 43
    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:     # PG check line 51; skips malformed with warning
    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:             # PG check line 69
    async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:           # PG check line 81
    async def revision(self, user_id: str, agent_id: str) -> str:                       # PG check line 109; max(updated_at) or ""
# `if _PG_OVERRIDES is not None:` occurs 5× (lines 43, 51, 69, 81, 109)

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/overrides_store.py — Postgres twin to mirror (save/load/remove/purge_agent/revision)
```

### Does NOT Exist
- ~~`parrot.handlers.toolkit_persistence_redis`~~ — created by this task.
- ~~`RedisDocumentStore.find(..., sort=...)`~~ — no sort argument; sort in Python if needed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_toolkit_overrides_redis.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py#ToolkitConfigService",
    "sym:packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py#UserToolkitOverride",
    "sym:packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py#set_toolkit_override_store"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Dispatch order: registered store (`_PG_OVERRIDES`) → `resolve_store_backend("TOOLKIT_OVERRIDES_STORE")`:
  `redis` → module-level Redis store, `documentdb` → `None`, `postgres` without registration → `RuntimeError`
  (today it silently falls back to DocumentDB — spec AC4).
- Lazy-import the Redis store module inside `_active_override_store()`.
- `purge_agent` returns the deleted overrides (vault clean-up needs their `secret_refs`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `toolkit_persistence_redis.py` — *why*: Redis twin of `PgToolkitOverrideStore`.
2. Add `_active_override_store()` and route the five checks through it — *why*: `redis` default + fail-closed postgres.
3. Write Redis tests; re-run the existing override suites.

### `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence_redis.py` (CREATE)
```python
"""Per-user toolkit overrides in Redis (FEAT-878): ``TOOLKIT_OVERRIDES_STORE=redis`` (the default)."""
from __future__ import annotations

import logging

from pydantic import ValidationError

from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_TOOLKIT_CONFIGS

from .toolkit_persistence import UserToolkitOverride

logger = logging.getLogger(__name__)


def _validate(doc: dict) -> UserToolkitOverride | None:
    try:
        return UserToolkitOverride.model_validate(doc)
    except ValidationError as exc:
        logger.warning("Skipping malformed toolkit override (agent=%s): %s", doc.get("agent_id"), type(exc).__name__)
        return None


class RedisToolkitOverrideStore:
    """``ToolkitConfigService`` methods over Redis; key (user_id, agent_id, slug)."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_TOOLKIT_CONFIGS)

    async def save(self, override: UserToolkitOverride) -> None:
        await self._docs.put(override.model_dump(mode="json"))

    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:
        docs = await self._docs.find({"user_id": user_id, "agent_id": agent_id})
        return [o for o in (_validate(d) for d in docs) if o is not None]

    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:
        return await self._docs.delete({"user_id": user_id, "agent_id": agent_id, "slug": slug})

    async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:
        """Delete every user's override for ``agent_ref`` and return them."""
        # FILL IN: delete_where({"agent_id": agent_ref}); validate each returned doc (skip malformed) — bounded by spec §3 M7.
        raise NotImplementedError

    async def revision(self, user_id: str, agent_id: str) -> str:
        return max((o.updated_at for o in await self.load(user_id, agent_id)), default="")
```
**Why**: `put` (full replace) matches the DocumentDB `$set` of the whole model; `agent_id` is indexed, so `purge_agent` does not scan.

### `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class ToolkitConfigService:' packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py)
# BEFORE `class ToolkitConfigService:` (verified: toolkit_persistence.py:38) insert:
_REDIS_OVERRIDES: Any = None


def _active_override_store() -> Any:
    """Registered store → it; redis → module-level RedisToolkitOverrideStore; documentdb → None;
    postgres with nothing registered → RuntimeError (fail closed)."""
    # FILL IN: lazy `from parrot.userstore import resolve_store_backend`; build _REDIS_OVERRIDES lazily from
    #   `.toolkit_persistence_redis` — bounded by spec §2 dispatch rule / AC4.
    raise NotImplementedError

# occurrences: 5 (verified: grep -c 'if _PG_OVERRIDES is not None:' .../toolkit_persistence.py) — disambiguate by method:
# FILL IN: in save (43), load (51), remove (69), purge_agent (81), revision (109) replace
#       if _PG_OVERRIDES is not None:
#           return await _PG_OVERRIDES.<op>(...)
#   with
#       store = _active_override_store()
#       if store is not None:
#           return await store.<op>(...)
```

### FILL IN checklist
- [ ] `purge_agent`
- [ ] `_active_override_store`
- [ ] five dispatch replacements

---

## Acceptance Criteria

- [ ] `TOOLKIT_OVERRIDES_STORE` unset → save/load/remove/purge_agent/revision on Redis
- [ ] `TOOLKIT_OVERRIDES_STORE=postgres` with no registered store raises `RuntimeError` (AC4); registered store still wins
- [ ] Existing suites (`test_toolkit_overrides.py`, `test_agenttalk_toolkit_overrides.py`, `test_overrides_store.py`) pass
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_toolkit_overrides_redis.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py -q`
- `pytest packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_overrides_store.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_identity.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_toolkit_overrides_redis.py
import pytest

from parrot.handlers import toolkit_persistence
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_overrides(monkeypatch):
    monkeypatch.delenv("TOOLKIT_OVERRIDES_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(toolkit_persistence, "_PG_OVERRIDES", None)
    monkeypatch.setattr(toolkit_persistence, "_REDIS_OVERRIDES", None)
    async with redis_test_settings(monkeypatch):
        yield ToolkitConfigService()


async def test_overrides_redis_store(redis_overrides):
    svc = redis_overrides
    await svc.save(UserToolkitOverride(user_id="35", agent_id="a1", slug="jira", params={"x": 1}))
    assert [o.slug for o in await svc.load("35", "a1")] == ["jira"]
    assert await svc.revision("35", "a1")
    assert await svc.remove("35", "a1", "jira") is True


async def test_purge_agent_returns_deleted(redis_overrides): ...
async def test_postgres_unregistered_fails_closed(monkeypatch): ...  # TOOLKIT_OVERRIDES_STORE=postgres → RuntimeError
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§3 M7)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5503 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
