# TASK-5502: BYOK in Redis — Studio keys handler and key source

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5501
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (server half). `StudioKeysHandler._list_keys/_persist_key/_remove_key` and
`key_source.user_byok_providers` each branch on `byok_store_setting() == "postgres"` and otherwise use
DocumentDB. With `BYOK_STORE` defaulting to `redis` (TASK-5501), these must use the Redis store. This task
adds one helper, `active_byok_store(app)`, and replaces the four branches with it.

---

## Scope

- Add `active_byok_store(app)` to `studio/byok.py`: `postgres` → `get_byok_store(app)`, `redis` →
  `get_user_llm_key_store()`, `documentdb` → `None`.
- Use it in `_list_keys`, `_persist_key`, `_remove_key` (byok.py) and `user_byok_providers` (key_source.py);
  DocumentDB code stays for `None`.
- Make `_mask` delegate to `mask_api_key` (one masking rule).
- Pin `BYOK_STORE=documentdb` in the Studio tests that fake DocumentDB; add a Redis handler test.

**NOT in scope**: core store/resolver (TASK-5501), Postgres store (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` | MODIFY | `active_byok_store`; three methods; `_mask` delegates |
| `packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py` | MODIFY | `user_byok_providers` via `active_byok_store` |
| `packages/ai-parrot-server/tests/studio/test_byok_redis.py` | CREATE | GET/POST/DELETE with `BYOK_STORE` unset (Redis) |
| `packages/ai-parrot-server/tests/studio/test_byok.py` | MODIFY | autouse pin `BYOK_STORE=documentdb` |
| `packages/ai-parrot-server/tests/studio/test_integration.py` | MODIFY | pin `BYOK_STORE=documentdb` where it fakes DocumentDB (line ~303) |
| `packages/ai-parrot-server/tests/studio/test_key_source_pa2.py` | MODIFY | pin `BYOK_STORE=documentdb` for cases not already setting `postgres` (only if they fail unpinned) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.broker import _UserLLMKeyResolver, byok_store_setting      # verified: studio/byok.py:17
from parrot.auth.broker import get_user_llm_key_store                       # TASK-5501
from parrot.auth.broker.byok_redis import mask_api_key                      # TASK-5501
from .storage.byok_store import get_byok_store                              # verified: studio/byok.py:123 (lazy import pattern)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/byok.py
from parrot.interfaces.documentdb import DocumentDb                           # line 19 — keep (documentdb path)
COLLECTION = "user_llm_keys"                                                  # line 31
def _mask(api_key: str) -> str:                                               # line 47
async def resolve_user_api_key(app: Any, user_id: str, provider: str) -> str | None:  # line 55 — via _UserLLMKeyResolver (unchanged)
class StudioKeysHandler(StudioBaseView):
    async def _list_keys(self, user, keyring) -> list[dict]:                  # line 120 — branch at 122
    def _masked_item(self, doc: dict, user, keyring) -> dict:                 # line 130 — documentdb path only
    async def _persist_key(self, user, provider: str, encrypted: str, plaintext: str) -> None:  # line 217 — branch at 219
    async def _remove_key(self, user, provider: str) -> None:                 # line 250 — branch at 252
# `if byok_store_setting() == "postgres":` occurs 3× in byok.py (122, 219, 252) → disambiguate by method.

# packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py
from parrot.auth.broker import byok_store_setting                             # line 14
from parrot.interfaces.documentdb import DocumentDb                           # line 17
async def user_byok_providers(app: Any, user_id: Any) -> frozenset[str]:      # line 75 — fails closed to frozenset() on any error

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/byok_store.py
def get_byok_store(app: Any) -> PgUserLLMKeyStore:                            # raises RuntimeError when unregistered
#   PgUserLLMKeyStore.put(user_id, provider, api_key) / delete(user_id, provider) -> bool / list_masked(user_id)
```

### Does NOT Exist
- ~~`active_byok_store`~~ — created by this task.
- ~~`RedisUserLLMKeyStore.put(..., encrypted)`~~ — Redis/Postgres stores take the plaintext and seal it themselves.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/studio/byok.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/studio/test_byok_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/studio/test_byok.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/studio/test_integration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/studio/test_key_source_pa2.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#_mask",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py#user_byok_providers",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/byok_store.py#get_byok_store"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `active_byok_store` and make `_mask` delegate — *why*: one store accessor, one mask rule.
2. Replace the three `== "postgres"` branches in byok.py — *why*: Redis is the default backend now.
3. Replace the branch in `user_byok_providers` — *why*: same rule; keep its fail-closed `frozenset()`.
4. Pin legacy tests; write the Redis handler test.

### `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` (MODIFY — helper + mask)
```python
# occurrences: 1 (verified: grep -c 'def _mask(api_key: str) -> str:' packages/ai-parrot-server/src/parrot/handlers/studio/byok.py)
# REPLACE the body of `def _mask(api_key: str) -> str:` (line 47) with `return mask_api_key(api_key)` (keep the docstring),
# then insert below it:
def active_byok_store(app: Any) -> Any | None:
    """The store BYOK_STORE selects: Postgres (registered at startup), core Redis store, or None for documentdb."""
    setting = byok_store_setting()
    if setting == "postgres":
        from .storage.byok_store import get_byok_store

        return get_byok_store(app)
    if setting == "redis":
        return get_user_llm_key_store()
    return None
# and extend the import at line 17: `from parrot.auth.broker import _UserLLMKeyResolver, byok_store_setting, get_user_llm_key_store`
# plus `from parrot.auth.broker.byok_redis import mask_api_key`.
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` (MODIFY — three methods)
```python
# occurrences: 3 (verified: grep -c 'if byok_store_setting() == "postgres":' .../studio/byok.py) — disambiguate by method:
# _list_keys (line 120): replace lines 122-125 with
        store = active_byok_store(self.request.app)
        if store is not None:
            return await store.list_masked(user.user_id)
# _persist_key (line 217): replace lines 219-223 with
        store = active_byok_store(self.request.app)
        if store is not None:
            await store.put(user.user_id, provider, plaintext)
            return
# _remove_key (line 250): replace lines 252-256 with
        store = active_byok_store(self.request.app)
        if store is not None:
            await store.delete(user.user_id, provider)
            return
# FILL IN: confirm each replaced block's exact line span before editing (the DocumentDB code after it stays).
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def user_byok_providers(app: Any, user_id: Any) -> frozenset[str]:' .../key_source.py)
# Inside the try of user_byok_providers (line 75), replace the `if byok_store_setting() == "postgres":` block with:
        from .byok import COLLECTION, active_byok_store

        store = active_byok_store(app)
        if store is not None:
            return frozenset(str(k["provider"]).lower() for k in await store.list_masked(user_id))
# keep the DocumentDB read below and the outer `except Exception` → frozenset().
# FILL IN: drop the now-unused `byok_store_setting` import (line 14) if nothing else in the module uses it.
```

### FILL IN checklist
- [ ] exact line spans of the three byok.py branches
- [ ] unused-import cleanup in key_source.py
- [ ] legacy pins (only where a module fails unpinned)

---

## Acceptance Criteria

- [ ] With `BYOK_STORE` unset, `/api/v1/astudio/keys` GET/POST/DELETE use Redis; `user_byok_providers` lists the stored providers
- [ ] `BYOK_STORE=postgres` and `=documentdb` behave as before (existing Studio tests pass)
- [ ] Masked previews identical to before (`_mask` == `mask_api_key`)
- [ ] `ruff check` clean on touched files

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/studio/test_byok_redis.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_byok.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_integration.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_key_source_pa2.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_keys_empty_api_key.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_byok_redis.py
import pytest

from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_byok(monkeypatch):
    # FILL IN: reuse the app/client setup of tests/studio/test_byok.py (same auth/session stubs), test keyring,
    #   BYOK_STORE unset, broker._REDIS_STORE reset, then `async with redis_test_settings(monkeypatch): yield`
    ...


async def test_studio_keys_redis(redis_byok): ...   # POST key → GET shows masked → DELETE → GET empty
async def test_user_byok_providers_redis(redis_byok): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§3 M6)
3. **Check dependencies** — TASK-5501 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5502 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
