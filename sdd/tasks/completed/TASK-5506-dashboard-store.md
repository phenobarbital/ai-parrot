# TASK-5506: `DashboardStore` protocol with DocumentDB and Redis implementations

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §2 "Dashboards", §3 Module 10 (store half). `DashboardHandler` / `DashboardTabHandler` contain 13
inline `async with DocumentDb() as db:` blocks. This task extracts their data access into a
`DashboardStore` protocol with two implementations: `DocumentDbDashboardStore` (today's queries, moved
verbatim) and `RedisDashboardStore`, chosen by `DASHBOARDS_STORE` (default `redis`). TASK-5507 rewires the
handlers onto it.

---

## Scope

- Create `parrot/handlers/dashboard_store.py` with `DashboardStore` (Protocol), `DocumentDbDashboardStore`,
  `RedisDashboardStore`, `get_dashboard_store()`.
- `DocumentDbDashboardStore` reproduces the exact DocumentDB queries/sorts/index definitions of
  `dashboard_handler.py` (listed in the contract).
- `RedisDashboardStore` uses `DASHBOARDS` / `DASHBOARD_TABS` specs; sorting in Python; `ensure_indexes()` is a no-op.
- `create_dashboard` / `create_tab` return `False` when the id already exists (TASK-5507 maps it to 409).
- Contract tests that run the same assertions against both implementations (DocumentDB mocked).

**NOT in scope**: handler changes (TASK-5507), `manager.py` (its `_ensure_dashboard_indexes` call stays; TASK-5507 changes the function body).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/dashboard_store.py` | CREATE | protocol + two stores + selector |
| `packages/ai-parrot-server/tests/unit/test_dashboard_store.py` | CREATE | contract tests (Redis db 15 + fake DocumentDB) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.documentdb import DocumentDb                     # verified: interfaces/documentdb.py:65 (handler imports it as ..interfaces.documentdb:30)
from parrot.userstore import RedisDocumentStore, resolve_store_backend   # TASK-5495/5496
from parrot.userstore.collections import DASHBOARDS, DASHBOARD_TABS      # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/documentdb.py — methods the DocumentDB store uses
async def read(...)                                    # line 370 — read(collection, query_or_None, sort=[(field, 1|-1)])
async def read_one(self, collection_name: str, query: dict, **kwargs) -> Optional[dict]:   # line 407
async def exists(self, collection_name: str, query: dict) -> bool:                         # line 422
async def write(self, collection_name: str, data, **kwargs) -> Any:                        # line 440 (insert)
async def update(self, collection_name: str, query: dict, update_data: dict, upsert: bool = False, **kwargs) -> Any:  # line 469
async def delete(self, collection_name: str, query: dict, **kwargs) -> Any:                # line 496
async def create_indexes(self, collection_name: str, keys: List[Union[str, tuple, dict]]) -> None:  # line 874

# packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py — the queries to move verbatim
DASHBOARDS_COLLECTION = "dashboards"; TABS_COLLECTION = "dashboard_tabs"            # lines 33-34
# _ensure_dashboard_indexes (line 37) index specs:
#   dashboards: [{"keys": [("dashboard_id", 1)], "unique": True}, "module_id", "user_id", {"keys": [("module_id", 1), ("user_id", 1)]}]
#   dashboard_tabs: [{"keys": [("tab_id", 1)], "unique": True}, "dashboard_id", "module_id", "user_id",
#                    {"keys": [("dashboard_id", 1), ("tab_id", 1)], "unique": True}]
# _get_one (111): read_one(dashboards, {"dashboard_id": id}); read(tabs, {"dashboard_id": id}, sort=[("index", 1)]); pop "_id"
# _get_list (138): read(dashboards, query or None, sort=[("created_at", -1)]) with optional module_id / user_id filters
# post (164): write(dashboards, doc)          put (208)/patch (259): exists + update({"dashboard_id"}, {"$set": fields})
# delete (312): exists; delete(tabs, {"dashboard_id"}); delete(dashboards, {"dashboard_id"})
# tab get (385): read_one(tabs, {"dashboard_id", "tab_id"}); tab list (400): read(tabs, {"dashboard_id"}, sort=[("index", 1)])
# tab post (418): exists(dashboards, {"dashboard_id"}) → 404; read(tabs, {"dashboard_id"}) for next index; write(tabs, doc)
# tab put (495)/patch (552): exists(tabs, {"dashboard_id","tab_id"}) + update(... {"$set": fields}); tab delete (607): exists + delete
```

### Does NOT Exist
- ~~`parrot.handlers.dashboard_store`~~ — created by this task.
- ~~`RedisDocumentStore.find(..., sort=...)`~~ — sort in Python (`created_at` desc, `index` asc).
- ~~A Postgres dashboard store~~ — not part of FEAT-878.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/dashboard_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/unit/test_dashboard_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py#DashboardHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py#DashboardTabHandler"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Returned documents never contain `_id` (both stores) — the handlers pop it today.
- `update_*` returns `False` when the target does not exist; `delete_dashboard` deletes the tabs first.
- `get_dashboard_store()` resolves `DASHBOARDS_STORE` at call time (a new instance per call is fine; stores are stateless).
- Tab ordering by `index` must tolerate missing/None `index` (sort key `(doc.get("index") is None, doc.get("index") or 0)`).

---

## Implementation Blueprint

### Steps (in order)
1. Write the Protocol and `get_dashboard_store()` — *why*: the handler contract TASK-5507 codes against.
2. Write `DocumentDbDashboardStore` from the queries in the contract — *why*: DocumentDB behaviour must not change.
3. Write `RedisDashboardStore` — *why*: `DASHBOARDS_STORE=redis` (default) needs no MongoDB.
4. Write one parametrised contract test running against both stores.

### `packages/ai-parrot-server/src/parrot/handlers/dashboard_store.py` (CREATE — protocol + selector)
```python
"""Dashboard persistence (FEAT-878): DashboardStore protocol, DocumentDB and Redis implementations."""
from __future__ import annotations

import logging
from typing import Any, Protocol

from parrot.interfaces.documentdb import DocumentDb
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import DASHBOARD_TABS, DASHBOARDS

logger = logging.getLogger("Parrot.DashboardStore")
DASHBOARDS_COLLECTION = "dashboards"
TABS_COLLECTION = "dashboard_tabs"


class DashboardStore(Protocol):
    """Everything DashboardHandler / DashboardTabHandler need; documents never carry ``_id``."""

    async def ensure_indexes(self) -> None: ...
    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None: ...
    async def list_dashboards(self, *, module_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]: ...
    async def create_dashboard(self, doc: dict[str, Any]) -> bool: ...
    async def dashboard_exists(self, dashboard_id: str) -> bool: ...
    async def update_dashboard(self, dashboard_id: str, fields: dict[str, Any]) -> bool: ...
    async def delete_dashboard(self, dashboard_id: str) -> bool: ...
    async def get_tab(self, dashboard_id: str, tab_id: str) -> dict[str, Any] | None: ...
    async def list_tabs(self, dashboard_id: str) -> list[dict[str, Any]]: ...
    async def create_tab(self, doc: dict[str, Any]) -> bool: ...
    async def tab_exists(self, dashboard_id: str, tab_id: str) -> bool: ...
    async def update_tab(self, dashboard_id: str, tab_id: str, fields: dict[str, Any]) -> bool: ...
    async def delete_tab(self, dashboard_id: str, tab_id: str) -> bool: ...


def get_dashboard_store() -> DashboardStore:
    """DASHBOARDS_STORE → RedisDashboardStore (default) or DocumentDbDashboardStore."""
    from parrot.userstore import resolve_store_backend

    return RedisDashboardStore() if resolve_store_backend("DASHBOARDS_STORE") == "redis" else DocumentDbDashboardStore()
```

### `packages/ai-parrot-server/src/parrot/handlers/dashboard_store.py` (CREATE — DocumentDB store)
```python
class DocumentDbDashboardStore:
    """Today's dashboard_handler.py queries, moved verbatim (see the Codebase Contract)."""

    async def ensure_indexes(self) -> None:
        # FILL IN: the two db.create_indexes(...) calls from dashboard_handler._ensure_dashboard_indexes, verbatim;
        #   log success like today ("Dashboard indexes created on '%s' and '%s'").
        raise NotImplementedError

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None:
        async with DocumentDb() as db:
            doc = await db.read_one(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id})
        if doc:
            doc.pop("_id", None)
        return doc or None

    async def list_dashboards(self, *, module_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
        query = {k: v for k, v in (("module_id", module_id), ("user_id", user_id)) if v}
        async with DocumentDb() as db:
            docs = await db.read(DASHBOARDS_COLLECTION, query or None, sort=[("created_at", -1)])
        for doc in docs:
            doc.pop("_id", None)
        return list(docs)

    async def create_dashboard(self, doc: dict[str, Any]) -> bool:
        async with DocumentDb() as db:
            if await db.exists(DASHBOARDS_COLLECTION, {"dashboard_id": doc["dashboard_id"]}):
                return False
            await db.write(DASHBOARDS_COLLECTION, doc)
        return True

    # FILL IN: dashboard_exists, update_dashboard (exists → update $set → True; else False),
    #   delete_dashboard (exists → delete tabs then dashboard), get_tab, list_tabs (sort index asc),
    #   create_tab, tab_exists, update_tab, delete_tab — each a verbatim lift of the handler query in the contract.
```

### `packages/ai-parrot-server/src/parrot/handlers/dashboard_store.py` (CREATE — Redis store)
```python
class RedisDashboardStore:
    """Dashboards and tabs in Redis; ensure_indexes is a no-op (indexes are part of the key layout)."""

    def __init__(self) -> None:
        self._dash = RedisDocumentStore(DASHBOARDS)
        self._tabs = RedisDocumentStore(DASHBOARD_TABS)

    async def ensure_indexes(self) -> None:
        return None

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None:
        return await self._dash.get({"dashboard_id": dashboard_id})

    async def list_dashboards(self, *, module_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
        where = {k: v for k, v in (("module_id", module_id), ("user_id", user_id)) if v}
        docs = await self._dash.find(where or None)
        return sorted(docs, key=lambda d: d.get("created_at") or "", reverse=True)

    async def create_dashboard(self, doc: dict[str, Any]) -> bool:
        return await self._dash.create(doc)

    async def delete_dashboard(self, dashboard_id: str) -> bool:
        await self._tabs.delete_where({"dashboard_id": dashboard_id})
        return await self._dash.delete({"dashboard_id": dashboard_id})

    async def list_tabs(self, dashboard_id: str) -> list[dict[str, Any]]:
        docs = await self._tabs.find({"dashboard_id": dashboard_id})
        return sorted(docs, key=lambda d: (d.get("index") is None, d.get("index") or 0))

    # FILL IN: dashboard_exists, update_dashboard (self._dash.update), get_tab, create_tab (self._tabs.create),
    #   tab_exists, update_tab, delete_tab — straightforward RedisDocumentStore calls.
```
**Why**: `create` (TASK-5496) gives atomic insert-if-absent, so duplicate creates return `False` without races;
deleting tabs before the dashboard mirrors the DocumentDB order.

### FILL IN checklist
- [ ] DocumentDB store: `ensure_indexes` + remaining nine methods (verbatim queries)
- [ ] Redis store: remaining seven methods
- [ ] contract test parametrised over both stores

---

## Acceptance Criteria

- [ ] Same contract assertions pass for both stores (CRUD, ordering, duplicate create → False, cascade delete)
- [ ] `get_dashboard_store()` returns the Redis store by default and the DocumentDB store with `DASHBOARDS_STORE=documentdb`
- [ ] No returned document contains `_id`
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_dashboard_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_dashboard_store.py
import pytest

from parrot.handlers import dashboard_store as ds
from parrot.userstore.testing import redis_test_settings


class _FakeDocumentDb:
    """In-memory DocumentDb stand-in (async context manager) supporting read/read_one/exists/write/update/delete/create_indexes."""
    # FILL IN: minimal equality-filter implementation; honour sort=[(field, ±1)]


@pytest.fixture(params=["redis", "documentdb"])
async def store(request, monkeypatch):
    if request.param == "documentdb":
        monkeypatch.setattr(ds, "DocumentDb", _FakeDocumentDb)
        yield ds.DocumentDbDashboardStore()
    else:
        async with redis_test_settings(monkeypatch):
            yield ds.RedisDashboardStore()


async def test_dashboard_store_contract(store): ...          # create/get/list(module_id,user_id)/update/exists
async def test_dashboard_duplicate_create_returns_false(store): ...
async def test_dashboard_delete_cascades_tabs(store): ...
async def test_tabs_sorted_by_index(store): ...
def test_selector_default_is_redis(monkeypatch): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Dashboards, §3 M10)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** — re-read the handler queries before lifting them
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5506 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note


- Task: TASK-5506
- Feature: redis-user-stores
- Implementation SHA: 45513995d2d2c1251aa5bdd7c363f87a39e16f74
- Closed at (UTC): 2026-11-11T02:09:02+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 325s · Tokens: n/a |
