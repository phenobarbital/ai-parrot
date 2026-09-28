# TASK-3825: Store meta API for ArangoDB and Postgres

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3822
**Assigned-to**: unassigned

---

## Context

Spec §8 Q2 ("a new meta per backend") / §3 Module 2. TASK-3822 defines
`BaseWikiStore.get_meta`/`set_meta`, which default to `NotImplementedError`, and implements
SQLite, in-memory and federated. This task implements the two server-hosted backends, so that
a shared plane also remembers its extractor fingerprint (TASK-3828).

Both backends already have a key/value home. No DDL change and no new collection are needed.

| Backend | Existing home | Scope | Implication |
|---|---|---|---|
| ArangoDB | the `wiki_meta` collection (`arango_store.py:50`, created at `:300`) | one database per wiki (`wiki_{wiki_name}`, `arango_store.py:8`) | one document per key, `_key = key` |
| Postgres | the `{schema}.meta (key text PRIMARY KEY, value text NOT NULL)` table (`graphindex/pg_schema.py:153`) | the schema is **shared** across wikis; pages are scoped by `namespace = wiki_name` (`postgres_store.py:12-17`) | the meta key **must be scoped too**: store it as `wiki:<wiki_name>:<key>`, or two wikis overwrite each other's fingerprint |

The Postgres `meta` table already holds graphindex's own `schema_version` row
(`pg_schema.py:373`). The `wiki:` prefix also keeps us clear of that row.

---

## Scope

- **`ArangoDBWikiStore.get_meta` / `set_meta`** over `META_COLLECTION`.
  - Reads go through `_query`, writes through `_execute`, both after `await self._ensure_init()`.
  - `set_meta` refuses when the store was opened `read_only=True` (the `__init__` flag at
    `arango_store.py:177`), in the same way its other writes refuse.
- **`PostgresWikiStore.get_meta` / `set_meta`** over `{self._schema}.meta`, with the key scoped
  as `wiki:{self._wiki_name}:{key}`. Use `pool = await self._ensure_pool()` and
  `async with pool.acquire() as conn`.
- Write tests. They are mock-based, following each backend's existing unit tests.

**NOT in scope**: base, SQLite, in-memory and federated (TASK-3822); the fingerprint
(TASK-3828); `parrot_tools/legal/wiki_store.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` | MODIFY | `get_meta`/`set_meta` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py` | MODIFY | `get_meta`/`set_meta` with wiki-scoped keys |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_meta_backends.py` | CREATE | mock-based unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore, META_COLLECTION   # arango_store.py:135, :50
from parrot.knowledge.wiki.postgres_store import PostgresWikiStore                   # postgres_store.py:127
```

### Existing Signatures to Use
```python
# arango_store.py
META_COLLECTION = "wiki_meta"                                                   # :50, occurrences: 1
class ArangoDBWikiStore(BaseWikiStore):                                         # :135
    def __init__(..., read_only: bool = False, ...)                             # :177
    async def _ensure_init(self) -> None:                                       # :476
    async def _query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:   # :488
    async def _execute(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]: # :506
    # write precedent: await self._execute(aql, {"docs": docs, "@collection": PAGES_COLLECTION})  # :563
# postgres_store.py
class PostgresWikiStore(BaseWikiStore):                                         # :127
    def __init__(self, dsn=None, *, wiki_name: str = "", schema: str = "graphindex", pool=None)  # :149-157
    self._wiki_name, self._schema                                              # :158-159
    async def _ensure_pool(self) -> asyncpg.Pool:                               # :166
    # usage precedent: `async with pool.acquire() as conn:`                     # :305
# graphindex/pg_schema.py:153
CREATE TABLE IF NOT EXISTS {schema}.meta (key text PRIMARY KEY, value text NOT NULL);
```

### Does NOT Exist
- ~~A `wiki_meta` Postgres table~~: use the existing `{schema}.meta`.
- ~~`ArangoDBWikiStore._assert_writable` refusing on its own~~: verify whether the arango store
  overrides `_assert_writable`. If it does not, refuse explicitly on `self._read_only` (or the
  actual attribute name; check `__init__`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_store_meta_backends.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py#ArangoDBWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py#PostgresWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Postgres SQL is parameterised (`$1`, `$2`). Only `self._schema` is interpolated, and it is an
  operator-controlled setting (see the `_ddl` docstring, `pg_schema.py:140-148`), exactly as the
  store already does.
- Arango: `key` is used as `_key`. Our only caller passes `extractor_fingerprint`, which is a
  valid key. Still, route it through the module's `document_key` helper if one is used for
  page keys (`arango_store.py:700`).

---

## Implementation Blueprint

### Steps (in order)
1. Implement Arango. 2. Implement Postgres with scoped keys. 3. Write the tests. 4. Mutation-check the Postgres scoping.

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` (MODIFY)
```python
# FILL IN: disambiguate — insert both methods inside `class ArangoDBWikiStore(BaseWikiStore):`
# (arango_store.py:135) right after `async def _execute(...)` ends (arango_store.py:506-512);
# quote that method's last 2 lines as the anchor after re-reading the file.

    async def get_meta(self, key: str) -> str | None:
        """Read one plane metadata value from ``wiki_meta`` (FEAT-609 Q2)."""
        await self._ensure_init()
        rows = await self._query(
            "FOR d IN @@collection FILTER d._key == @key RETURN d.value",
            {"@collection": META_COLLECTION, "key": key},
        )
        return str(rows[0]) if rows else None

    async def set_meta(self, key: str, value: str) -> None:
        """Upsert one plane metadata value into ``wiki_meta``."""
        # FILL IN: refuse on a read-only store the way this class's other writes do —
        # bounded by `read_only` (arango_store.py:177)
        await self._ensure_init()
        await self._execute(
            "UPSERT { _key: @key } INSERT { _key: @key, value: @value } "
            "UPDATE { value: @value } IN @@collection",
            {"@collection": META_COLLECTION, "key": key, "value": value},
        )
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py` (MODIFY)
```python
# FILL IN: disambiguate — insert inside `class PostgresWikiStore(BaseWikiStore):` right after
# `async def close(self) -> None:` ends (postgres_store.py:177-181); quote its last 2 lines.

    def _meta_key(self, key: str) -> str:
        """Scope ``key`` to this wiki: the ``meta`` table is shared by every wiki in the schema."""
        return f"wiki:{self._wiki_name}:{key}"

    async def get_meta(self, key: str) -> str | None:
        """Read one plane metadata value (FEAT-609 Q2)."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            value = await conn.fetchval(
                f"SELECT value FROM {self._schema}.meta WHERE key = $1", self._meta_key(key)
            )
        return None if value is None else str(value)

    async def set_meta(self, key: str, value: str) -> None:
        """Upsert one plane metadata value (FEAT-609 Q2)."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self._schema}.meta (key, value) VALUES ($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                self._meta_key(key),
                value,
            )
```

### `packages/ai-parrot/tests/knowledge/wiki/test_store_meta_backends.py` (CREATE)
```python
"""FEAT-609 Q2: get_meta/set_meta on the server-hosted backends (mocked I/O)."""

from __future__ import annotations

import pytest


async def test_postgres_meta_keys_are_wiki_scoped() -> None:
    # FILL IN: PostgresWikiStore(wiki_name="a", pool=<mock pool whose acquire() yields a
    # mock conn>) — build the mocks the way test_postgres_store.py does; assert the key
    # bound to $1 is "wiki:a:extractor_fingerprint" for both get and set — bounded by the
    # shared-schema scoping rule (Context table)
    ...


async def test_postgres_two_wikis_do_not_collide() -> None:
    # FILL IN: wiki_name="a" and "b" produce different bound keys
    ...


async def test_arango_meta_upsert_and_read() -> None:
    # FILL IN: mock _db the way tests/knowledge/wiki/test_arango_store.py does; set_meta
    # issues an UPSERT into wiki_meta, get_meta returns the queried value, None when empty
    ...


async def test_arango_meta_read_only_refuses() -> None:
    # FILL IN: read_only=True store -> set_meta raises; get_meta still works
    ...
```

### FILL IN checklist
- [ ] Exact insertion anchors in both files (re-read, quote two lines).
- [ ] Arango read-only refusal. Bound: match the class's existing write refusal.
- [ ] Mock harnesses. Bound: reuse `test_postgres_store.py` and
  `tests/knowledge/wiki/test_arango_store.py` patterns.

---

## Acceptance Criteria

- [ ] Arango: `set_meta` then `get_meta` round-trips through `wiki_meta`, and a read-only store
      refuses `set_meta`.
- [ ] Postgres: keys are stored as `wiki:<wiki_name>:<key>`, and two wikis never collide
      (mutation-checked: drop `_meta_key` and see `test_postgres_two_wikis_do_not_collide` go RED).
- [ ] No DDL change: `pg_schema.py` is untouched.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_meta_backends.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_postgres_store.py -q`
- `pytest tests/knowledge/wiki/test_arango_store.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Confirm TASK-3822 is `done`, and verify the contract.
3. Implement, validate, mutation-check, and stage only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3825 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
