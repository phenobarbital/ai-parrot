# TASK-5496: RedisDocumentStore, collection registry and Redis test helper

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5495
**Assigned-to**: unassigned

---

## Context

Spec §2 "Redis primitive" + "Document shape rule", §3 Module 2. Every per-domain Redis store
(vault, BYOK, OAuth2, overrides, MCP, Telegram, dashboards), the copy CLI and the rotation targets are
thin wrappers over one keyed-document primitive with secondary indexes. This task builds it, the
eight `CollectionSpec`s, and the db-15 test helper all Redis-backed tests use (`fakeredis` is not
installed).

---

## Scope

- Implement `CollectionSpec`, the 8 collection constants, `USER_STORE_COLLECTIONS`, `COLLECTION_SWITCH`.
- Implement `RedisDocumentStore` (get / put / create / upsert / update / delete / exists / find / delete_where / scan)
  with the key layout of spec §2 and transactional index maintenance (`WATCH`/`MULTI`/`EXEC`, bounded retry).
- Implement `parrot.userstore.testing.redis_test_settings` (db 15, unique prefix, prefix-only cleanup, skip when unreachable).
- Export `RedisDocumentStore`, `CollectionSpec`, `USER_STORE_COLLECTIONS`, `COLLECTION_SWITCH` from `parrot.userstore`.
- Write tests against the real local Redis (db 15).

**NOT in scope**: any domain store, any service change, the copy CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/userstore/collections.py` | CREATE | `CollectionSpec` + 8 specs + switch map |
| `packages/ai-parrot/src/parrot/userstore/redis_documents.py` | CREATE | `RedisDocumentStore` |
| `packages/ai-parrot/src/parrot/userstore/testing.py` | CREATE | `redis_test_settings` async context manager |
| `packages/ai-parrot/src/parrot/userstore/__init__.py` | MODIFY | add exports |
| `packages/ai-parrot/tests/userstore/test_redis_documents.py` | CREATE | tests on real Redis db 15 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.userstore.settings import get_user_store_redis, key_prefix, SWITCHES  # created by TASK-5495
import redis.asyncio as aioredis       # redis 5.2.1; WatchError lives in redis.exceptions
from redis.exceptions import WatchError
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/userstore/__init__.py (TASK-5495) — ends with the __all__ list; append to it.
# redis.asyncio (5.x): client.pipeline(transaction=True) → async context manager;
#   pipe.watch(*keys); pipe.multi(); pipe.set/sadd/srem/delete(...); await pipe.execute()
#   client.mget(keys) → list[str | None]; client.sinter(keys) / client.smembers(key) → set[str]
#   client.scan_iter(match=...) → async iterator
```

### Does NOT Exist
- ~~`fakeredis`~~ — not installed; use the real Redis on db 15.
- ~~`DocumentDb.upsert` / `DocumentDb.find`~~ — unrelated; this store has its own API.
- ~~TTL on user-store keys~~ — secrets have no TTL (spec §7).
- ~~Range / regex / `$in` filters~~ — `find` supports equality only; callers sort.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/userstore/collections.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/userstore/redis_documents.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/userstore/testing.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/userstore/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/userstore/test_redis_documents.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Key layout (spec §2): document `{prefix}:{collection}:d:{k1}:{k2}…` (JSON string), index
  `{prefix}:{collection}:i:{field}:{value}` (SET of ids), all `{prefix}:{collection}:all` (SET of ids).
  Id = the encoded key parts joined by `:`; each part is `urllib.parse.quote(str(v), safe="")`.
- Key and index fields compare as strings: `{"user_id": 35}` and `{"user_id": "35"}` address the same document.
- JSON encode with a default that turns `datetime`/`date` into `isoformat()` and anything else into `str`;
  `sort_keys=True`. Documents never contain `_id`.
- Every write that touches indexes runs in one `WATCH doc_key` → read old → `MULTI` → write doc + SREM old
  index ids + SADD new ones → `EXEC`; retry on `WatchError` up to 5 times, then raise `RuntimeError`.
- `find` skips ids whose document is gone (stale index entry) instead of failing.
- `self.logger = logging.getLogger("parrot.userstore.redis")`; never log document values.

---

## Implementation Blueprint

### Steps (in order)
1. Write `collections.py` — *why*: `RedisDocumentStore` and later tasks import the specs from one place.
2. Write `redis_documents.py` and complete the `FILL IN`s — *why*: atomic index maintenance is the core risk (spec §7 "Index consistency").
3. Write `testing.py` — *why*: every Redis-backed test in FEAT-878 uses it (db 15, prefix cleanup).
4. Extend `__init__.py` exports; write tests; run validation.

### `packages/ai-parrot/src/parrot/userstore/collections.py` (CREATE)
```python
"""FEAT-878 collection registry: key/index fields per user-store collection (spec §2 Data Models)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionSpec:
    """One collection: its name, the fields forming the document key, and the indexed fields."""

    name: str
    key_fields: tuple[str, ...]
    index_fields: tuple[str, ...] = ()


USER_CREDENTIALS = CollectionSpec("user_credentials", ("user_id", "name"), ("user_id",))
USER_LLM_KEYS = CollectionSpec("user_llm_keys", ("user_id", "provider"), ("user_id",))
USER_TOOLKIT_CONFIGS = CollectionSpec("user_toolkit_configs", ("user_id", "agent_id", "slug"), ("user_id", "agent_id"))
USER_MCP_CONFIGS = CollectionSpec("user_mcp_configs", ("user_id", "agent_id", "server_name"), ("user_id", "agent_id"))
TELEGRAM_USER_MCP_CONFIGS = CollectionSpec("telegram_user_mcp_configs", ("user_id", "name"), ("user_id",))
USERS_INTEGRATIONS = CollectionSpec("users_integrations", ("user_id", "provider"), ("user_id",))
DASHBOARDS = CollectionSpec("dashboards", ("dashboard_id",), ("module_id", "user_id"))
DASHBOARD_TABS = CollectionSpec("dashboard_tabs", ("dashboard_id", "tab_id"), ("dashboard_id",))

USER_STORE_COLLECTIONS: dict[str, CollectionSpec] = {
    spec.name: spec
    for spec in (USER_CREDENTIALS, USER_LLM_KEYS, USER_TOOLKIT_CONFIGS, USER_MCP_CONFIGS,
                 TELEGRAM_USER_MCP_CONFIGS, USERS_INTEGRATIONS, DASHBOARDS, DASHBOARD_TABS)
}

COLLECTION_SWITCH: dict[str, str] = {
    "user_credentials": "VAULT_STORE",
    "user_llm_keys": "BYOK_STORE",
    "user_toolkit_configs": "TOOLKIT_OVERRIDES_STORE",
    "user_mcp_configs": "MCP_CONFIGS_STORE",
    "telegram_user_mcp_configs": "TELEGRAM_MCP_STORE",
    "users_integrations": "INTEGRATIONS_STORE",
    "dashboards": "DASHBOARDS_STORE",
    "dashboard_tabs": "DASHBOARDS_STORE",
}
```
**Why this shape**: verbatim from the spec registry table; `COLLECTION_SWITCH` lets the copy CLI and the
rotation targets find a collection's switch without importing service code.

### `packages/ai-parrot/src/parrot/userstore/redis_documents.py` (CREATE)
```python
"""Keyed JSON documents with secondary indexes over redis.asyncio (FEAT-878, spec §2 Redis primitive)."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import redis.asyncio as aioredis
from redis.exceptions import WatchError

from .collections import CollectionSpec
from .settings import get_user_store_redis, key_prefix

_MAX_RETRIES = 5


def _json_default(value: Any) -> str:
    return value.isoformat() if isinstance(value, (datetime, date)) else str(value)


def _dumps(document: Mapping[str, Any]) -> str:
    return json.dumps(dict(document), default=_json_default, sort_keys=True)


class RedisDocumentStore:
    """Keyed JSON documents for one CollectionSpec. Equality filters only; no TTL."""

    def __init__(self, spec: CollectionSpec, *, client: aioredis.Redis | None = None,
                 prefix: str | None = None) -> None:
        self.spec = spec
        self._client = client
        self._prefix = prefix
        self.logger = logging.getLogger("parrot.userstore.redis")

    @property
    def client(self) -> aioredis.Redis:
        """Injected client, else the per-loop user-store client."""
        return self._client or get_user_store_redis()

    def _base(self) -> str:
        return f"{self._prefix or key_prefix()}:{self.spec.name}"

    def _doc_id(self, key: Mapping[str, Any]) -> str:
        """Encoded key parts joined by ':'. ValueError when a key field is missing or None."""
        # FILL IN: for each spec.key_fields, require key[f] is not None, then quote(str(v), safe="") — bounded by spec §2.
        raise NotImplementedError

    def _doc_key(self, doc_id: str) -> str:
        return f"{self._base()}:d:{doc_id}"

    def _index_key(self, field: str, value: Any) -> str:
        return f"{self._base()}:i:{field}:{quote(str(value), safe='')}"

    def _all_key(self) -> str:
        return f"{self._base()}:all"

    async def _write(self, doc_id: str, build: "Callable[[dict | None], dict | None]") -> dict | None:
        """WATCH/MULTI/EXEC: ``build(old) -> new`` (None deletes); keeps index sets and 'all' consistent."""
        # FILL IN: pipeline(transaction=True); watch doc key; read+decode old; new = build(old);
        #   multi(); set or delete the doc; srem old index ids / sadd new ones (only changed fields);
        #   sadd/srem the 'all' set; execute(); on WatchError retry up to _MAX_RETRIES then RuntimeError.
        #   Return the new document (or the deleted old one when new is None) — bounded by spec §7 Index consistency.
        raise NotImplementedError
```
**Why this shape**: one `_write` helper carries the transaction so `put`, `upsert`, `update`, `delete`
cannot drift apart; ids encode the key so a document is addressable without a scan. Add
`from collections.abc import Callable` to the imports when you write `_write`.

### `packages/ai-parrot/src/parrot/userstore/redis_documents.py` (CREATE, continued — public API)
```python
    async def get(self, key: Mapping[str, Any]) -> dict[str, Any] | None:
        """Document for the full key, or None."""
        raw = await self.client.get(self._doc_key(self._doc_id(key)))
        return json.loads(raw) if raw else None

    async def exists(self, key: Mapping[str, Any]) -> bool:
        return bool(await self.client.exists(self._doc_key(self._doc_id(key))))

    async def put(self, document: Mapping[str, Any]) -> None:
        """Replace the whole document (key taken from the document)."""
        clean = {k: v for k, v in document.items() if k != "_id"}
        await self._write(self._doc_id(clean), lambda _old: clean)

    async def create(self, document: Mapping[str, Any]) -> bool:
        """Insert only when absent, atomically (False and no write when the key exists). Used for 409 semantics."""
        # FILL IN: _write with a builder that keeps `old` unchanged when it exists; report whether a document was created
        #   — bounded by TASK-5506 duplicate-create 409 (spec AC10).
        raise NotImplementedError

    async def upsert(self, key: Mapping[str, Any], set_fields: Mapping[str, Any], *,
                     on_insert: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """$set/$setOnInsert semantics; returns the stored document."""
        # FILL IN: build = old merged with set_fields; on creation start from {**key, **on_insert} — bounded by spec §3 M2.
        raise NotImplementedError

    async def update(self, key: Mapping[str, Any], set_fields: Mapping[str, Any]) -> bool:
        """Merge into an existing document; False (no write) when absent."""
        # FILL IN: build returns None-sentinel "no change" when old is None; must not create — bounded by spec §3 M2.
        raise NotImplementedError

    async def delete(self, key: Mapping[str, Any]) -> bool:
        """True when a document was removed."""
        return (await self._write(self._doc_id(key), lambda _old: None)) is not None

    async def find(self, where: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Documents matching every equality in ``where`` (all documents when None/empty)."""
        # FILL IN: full key in where → get(); else SINTER of index sets for indexed fields present, or SMEMBERS(all);
        #   MGET in chunks; skip missing; filter every where item comparing str(doc.get(f)) == str(v) — bounded by spec §2.
        raise NotImplementedError

    async def delete_where(self, where: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Delete and return every matching document (each delete is its own transaction)."""
        deleted = []
        for doc in await self.find(where):
            if await self.delete(doc):
                deleted.append(doc)
        return deleted

    async def scan(self) -> AsyncIterator[dict[str, Any]]:
        """Every document, ordered by its encoded id."""
        # FILL IN: SMEMBERS(all) sorted, MGET in chunks, yield decoded documents (skip missing) — bounded by spec §3 M2.
        raise NotImplementedError
        yield {}  # pragma: no cover — keeps this an async generator
```
**Why**: `update` must never create (CredentialsHandler PUT relies on an explicit existence check; DocumentDB
`update_one` without upsert also does not create). `delete_where` returns what it removed because
`purge_agent` needs it for vault clean-up.

### `packages/ai-parrot/src/parrot/userstore/testing.py` (CREATE)
```python
"""Test support for FEAT-878 Redis-backed tests: real Redis db 15, unique prefix, prefix-only cleanup."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

TEST_REDIS_URL = "redis://localhost:6379/15"


@asynccontextmanager
async def redis_test_settings(monkeypatch: Any) -> AsyncIterator[str]:
    """Point the user store at db 15 with a unique prefix; yield the prefix; delete only its keys."""
    import pytest  # test-only dependency, imported lazily

    from .settings import close_user_store_redis, get_user_store_redis

    prefix = f"test:feat878:{uuid.uuid4().hex}"
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_PREFIX", prefix)
    client = get_user_store_redis()
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001 — any connection failure means "no Redis here"
        await close_user_store_redis()
        pytest.skip(f"local Redis unreachable: {type(exc).__name__}")
    try:
        yield prefix
    finally:
        # FILL IN: scan_iter(match=f"{prefix}:*") and delete in batches — NEVER FLUSHDB (shared server); then close_user_store_redis().
        pass
```
**Why**: the repository has no `fakeredis`; other sessions share the local Redis, so cleanup must be prefix-scoped.

### `packages/ai-parrot/src/parrot/userstore/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^__all__ = \[' packages/ai-parrot/src/parrot/userstore/__init__.py after TASK-5495)
# AFTER the settings import block, add:
from .collections import COLLECTION_SWITCH, USER_STORE_COLLECTIONS, CollectionSpec
from .redis_documents import RedisDocumentStore
# and extend __all__ with: "COLLECTION_SWITCH", "USER_STORE_COLLECTIONS", "CollectionSpec", "RedisDocumentStore"
```

### FILL IN checklist
- [ ] `_doc_id` — encoding + missing-field ValueError
- [ ] `_write` — WATCH/MULTI/EXEC with index diff + retry; bounded by §7
- [ ] `create` — atomic insert-if-absent
- [ ] `upsert` / `update` — `$setOnInsert` semantics; update never creates
- [ ] `find` — index intersection, string comparison, stale-id skip
- [ ] `scan` — deterministic order
- [ ] `redis_test_settings` cleanup — prefix-only

---

## Acceptance Criteria

- [ ] All 8 specs match the spec §2 registry table
- [ ] Concurrent upserts on one key leave exactly one id per index set (spec §4 `test_concurrent_upserts_keep_indexes`)
- [ ] Changing an indexed field moves the id between index sets
- [ ] `find` with indexed + non-indexed filters; `find()` returns all; `35`/`"35"` equivalence
- [ ] Tests skip cleanly when Redis is unreachable; no key outside the test prefix is touched
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/userstore/test_redis_documents.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/userstore/test_redis_documents.py
import asyncio
import pytest

from parrot.userstore import CollectionSpec, RedisDocumentStore
from parrot.userstore.testing import redis_test_settings

SPEC = CollectionSpec("t_docs", ("user_id", "name"), ("user_id", "kind"))


@pytest.fixture
async def store(monkeypatch):
    async with redis_test_settings(monkeypatch):
        yield RedisDocumentStore(SPEC)


async def test_put_get_delete_roundtrip(store):
    await store.put({"user_id": 35, "name": "a:b/c", "kind": "x", "v": 1})
    assert (await store.get({"user_id": "35", "name": "a:b/c"}))["v"] == 1
    assert await store.delete({"user_id": 35, "name": "a:b/c"}) is True
    assert await store.get({"user_id": 35, "name": "a:b/c"}) is None


async def test_upsert_on_insert_only_once(store): ...
async def test_update_absent_returns_false(store): ...
async def test_create_only_when_absent(store): ...   # second create of the same key → False, document unchanged
async def test_index_follows_field_change(store): ...
async def test_find_intersects_indexes(store): ...
async def test_delete_where_returns_docs(store): ...
async def test_concurrent_upserts_keep_indexes(store):
    await asyncio.gather(*(store.upsert({"user_id": 1, "name": "n"}, {"kind": f"k{i % 3}"}) for i in range(20)))
    # FILL IN: exactly one of the k0/k1/k2 index sets holds the id; the 'all' set holds it once
async def test_missing_key_field_raises(store): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Redis primitive + Document shape rule, §3 M2, §7 Index consistency)
3. **Check dependencies** — TASK-5495 must be `done`
4. **Verify the Codebase Contract** before writing code
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5496 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
