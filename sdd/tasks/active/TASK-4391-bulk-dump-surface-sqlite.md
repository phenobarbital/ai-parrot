# TASK-4391: Bulk-transfer surface — `BaseWikiStore.dump_*` defaults, SQLite natives, `SchemaStore.dump_columns`, `SQLitePersistence.export_commits` / `import_commits`

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 12 — bulk-read surface part; AC27; §4 `test_dump_bulk_surface_parity`)
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`wikitoolkit migrate` (M12, resolved §8 Q2) copies a plane between two registered backends
**through the contracts only**. Today the only bulk readers are `dump_pages` / `dump_edges`
(`wiki/store.py:790-793`). This task adds the **additive** bulk-transfer surface on the
existing (non-HelixDB) classes so the migration engine (TASK-4394) has something to read and
the HelixDB natives (TASK-4393) have a reference to match:

- `BaseWikiStore.dump_attrs` (derivable default) / `dump_meta` / `dump_symbols` /
  `dump_embeddings` (defaults raise `NotImplementedError` ⇒ migrate reports the part `unsupported`);
- native, key-ordered implementations on `SQLiteWikiStore`;
- `SchemaStore.dump_columns`;
- `SQLitePersistence.export_commits` / `import_commits` (the SQLite half of the
  `GraphHistoryTransfer` capability; the Protocol itself lives in `wiki/migrate.py`, TASK-4394).

Non-goal (spec §1): **no existing method changes behaviour**; every pre-existing SQLite test
must pass unchanged.

---

## Scope

- Add four concrete (non-abstract) methods to `BaseWikiStore` right after the abstract `dump_edges`.
- Add four native overrides to `SQLiteWikiStore` right after its `dump_edges`.
- Add `SchemaStore.dump_columns()` after `columns_for`.
- Add `SQLitePersistence.export_commits(ctx, *, after_seq=0, limit=500)` and
  `import_commits(ctx, commits, *, replace=False)` between `get_commit` and `list_commits`.
- Write `packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py`, parametrised over a
  `backend` fixture whose only value today is `"sqlite"` (TASK-4393 adds `"helix-memory"`).

**NOT in scope**: HelixDB natives (TASK-4393); `GraphHistoryTransfer`, `MigrationReport`,
`migrate_*` (TASK-4394); the CLI (TASK-4395); `ArangoDBWikiStore` / `PostgresWikiStore` /
`InMemoryWikiStore` overrides (they inherit the base defaults by design, spec §2 "Migration");
`dump_pages` / `dump_edges` changes; `SourceManifestBackend.list_sources` (already exists in FEAT-540).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `BaseWikiStore` dump defaults + `SQLiteWikiStore` natives |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py` | MODIFY | `SchemaStore.dump_columns` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` | MODIFY | `export_commits` / `import_commits` |
| `packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py` | CREATE | backend-parametrised bulk-surface tests |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca` (raw `grep -n -F` / `grep -c -F`).

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord   # store.py:697, :1092, :433
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord                       # symbols.py:58 (SymbolRecord); store.py imports it only under TYPE_CHECKING (:46-47)
from parrot.knowledge.wiki.schema.store import SchemaStore                               # schema/store.py:48
from parrot.knowledge.wiki.schema.models import ColumnRecord                             # schema/models.py:34
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence                 # persist_sqlite.py:139
from parrot.knowledge.graphindex.schema import GraphUpdate, NodeKind, UniversalNode     # schema.py:233, :36, :149
```

### Existing Signatures to Use
```python
# wiki/store.py
def _pack_vector(vector: list[float]) -> bytes                     # :379
def _unpack_vector(blob: bytes) -> list[float]                     # :384
def _row_to_symbol_record(row: aiosqlite.Row) -> SymbolRecord      # :396 (decorators are not persisted)
class BaseWikiStore(ABC):                                          # :697
    supports_attrs: bool = False                                   # :716
    async def get_attrs(self, concept_id: str) -> dict[str, str]   # :718 (default {})
    @abstractmethod async def dump_pages(self) -> list[dict[str, Any]]: ...   # :790
    @abstractmethod async def dump_edges(self) -> list[dict[str, Any]]: ...   # :793
    async def get_meta(self, key) / set_meta(key, value)           # :858 / :872 (defaults raise NotImplementedError)
    async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int   # :958 (default 0)
class SQLiteWikiStore(BaseWikiStore):                              # :1092
    async def _read(self) -> AsyncIterator[aiosqlite.Connection]   # :1334 (row_factory gives name access)
    async def _attrs_table_present(self, conn) -> bool             # :1803
    async def upsert_attrs(...)                                    # :2027  — page_attrs(concept_id, key, value) PK(concept_id, key) (:57-64)
    async def upsert_embedding(self, concept_id, vector, model="") # :2160 — embeddings(concept_id PK, vector BLOB, model) (:141-145)
    async def upsert_symbols(self, symbols, source_id=None) -> int # :2183 — symbols(concept_id PK, …, source_id) (:150-171)
    async def get_meta / set_meta                                  # :2346 / :2353 — meta(key PK, value) (:73-76)
    async def dump_pages(self)                                     # :2595 — ORDER BY concept_id
    async def dump_edges(self)                                     # :2609
    async def stats(self)                                          # :2615

# wiki/schema/store.py
class SchemaStore(SQLiteWikiStore):                                # :48 — columns(table_id, ordinal, name, data_type, nullable, dflt,
                                                                   #   comment, is_primary_key, fk_target) PK(table_id, name) (:15-21)
    def _column_from_row(row) -> ColumnRecord                      # :78 (staticmethod)
    async def upsert_columns(self, columns: list[ColumnRecord]) -> int   # :120
    async def columns_for(self, table_id: str) -> list[ColumnRecord]     # :126 — ORDER BY ordinal
    async def find_columns(...)                                    # :135

# graphindex/persist_sqlite.py
class SQLitePersistence:                                           # :139
    def __init__(self, db_dir: Path) -> None                       # :154
    def _db_path(self, ctx) -> Path                                # :162 — <db_dir>/<tenant_id>.db
    async def _connect(self, ctx) -> AsyncIterator[aiosqlite.Connection]   # :174 (creates the db + schema; caller commits)
    async def get_commit(self, ctx, commit_id) -> Optional[dict]   # :778 — row + decoded payload + items[{item_type, item_key, prior(JSON text)}]
    async def list_commits(self, ctx, run_id=None, agent_id=None, limit=50)  # :807
    async def revert_commit(self, ctx, commit_id) -> dict          # :846 — conflict ordering uses graph_commits.rowid (:886-893)
# graph_commits(commit_id PK TEXT, op, agent_id, run_id, asserted_by, reason, committed_at, payload, reverted_at) — rowid table (:83-93)
# graph_commit_items(commit_id, item_type, item_key, prior) PK(commit_id, item_type, item_key) (:97-103)
```

### Blueprint anchors (`grep -c -F`)
| File | Anchor | Line | Count |
|---|---|---|---|
| `wiki/store.py` | `    async def dump_edges(self) -> list[dict[str, Any]]: ...` | 793 | 1 |
| `wiki/store.py` | `        """Return every edge row (bulk export path)."""` | 2610 | 1 |
| `wiki/store.py` | `            async with conn.execute("SELECT src, dst, rel FROM edges ORDER BY src, dst, rel") as cur:` | 2612 | 1 |
| `wiki/schema/store.py` | `    async def columns_for(self, table_id: str) -> list[ColumnRecord]:` | 126 | 1 |
| `wiki/schema/store.py` | `    async def find_columns(` | 135 | 1 |
| `graphindex/persist_sqlite.py` | `    async def list_commits(` | 807 | 1 |

`    async def stats(self) -> dict[str, Any]:` occurs **2** times in `wiki/store.py` (`:796` abstract with ` ...`, `:2615` SQLite) — do not use it as an anchor.

### Does NOT Exist
- ~~`BaseWikiStore.dump_attrs` / `dump_meta` / `dump_symbols` / `dump_embeddings`~~, ~~`SchemaStore.dump_columns`~~, ~~`SQLitePersistence.export_commits` / `import_commits`~~ — created here.
- ~~A `seq` column in `graph_commits`~~ — export derives `seq` from `rowid`; import writes `rowid = seq`.
- ~~`GraphHistoryTransfer`~~ — TASK-4394 (`wiki/migrate.py`); do not define it here.
- ~~`SQLiteWikiStore.initialize()` / `close()` required before use~~ — the store opens lazily in `_read()` / `_write()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.dump_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.dump_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._read",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._attrs_table_present",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#_unpack_vector",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#_row_to_symbol_record",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore.columns_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore._column_from_row",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence.get_commit",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence._connect"
  ]
}
```

---

## Implementation Notes

### Row contracts (cross-task — TASK-4393 natives and TASK-4394 must match them exactly)
- `dump_attrs()` → `[{"concept_id", "key", "value"}]` ordered by `(concept_id, key)`; `[]` when the plane has no `page_attrs` table.
- `dump_meta()` → `dict[str, str]` (insertion order = key order).
- `dump_symbols()` → `list[SymbolRecord]` ordered by `concept_id` (`sym_concept_id(rel_path, qualname)`).
- `dump_embeddings()` → `[{"concept_id", "vector": list[float], "model"}]` ordered by `concept_id`.
- `dump_columns()` → `list[ColumnRecord]` ordered by `(table_id, ordinal)`.
- `export_commits(ctx, *, after_seq=0, limit=500)` → commits with `seq > after_seq` ascending, at most `limit`; each row = every `graph_commits` column + `seq` (`rowid`) + `payload` **decoded** (dict) + `items` `[{item_type, item_key, prior}]` with `prior` as **JSON text** (same as `get_commit`); `[]` when the tenant db does not exist (do NOT create it).
- `import_commits(ctx, commits, *, replace=False) -> int` (commits written):
  - `replace=True` ⇒ delete every `graph_commits` / `graph_commit_items` row first, then insert;
  - `replace=False` ⇒ append-only: raise `ValueError` naming the conflict when an incoming `commit_id` already exists or an incoming `seq` is ≤ the current max `rowid` (this lets TASK-4394 import in batches: first batch with the user's `--replace`, later batches with `replace=False`, and lets `--resume` continue);
  - insert `graph_commits` with explicit `rowid = seq` and `payload` re-encoded with `orjson`; items verbatim; one transaction; it never touches `nodes` / `edges` (the graph part is copied by `persist_graph`).

### Spec drift / known limits (record, do not redesign)
- **`dump_symbols` loses `symbols.source_id`** (and `SymbolRecord.decorators`, never persisted): `SymbolRecord` (`symbols.py:58`) has no `source_id` field, so a migrated symbol plane gets `source_id = NULL` unless TASK-4394 groups by source. Kept as spec'd (`list[SymbolRecord]`); flagged for TASK-4394.
- Spec §3 M12 places the SQLite natives "after `:2465`" — the real `dump_edges` is now at `:2609`.

### Key Constraints
- Purely additive: no existing method body or signature changes; the four base methods are **concrete** (not `@abstractmethod`) so out-of-tree subclasses keep instantiating.
- Base `dump_attrs` default: iterate `dump_pages()` ids, `get_attrs()` each, emit sorted rows (works on Arango/Postgres; returns `[]` where attrs are unsupported).
- Use `self._read()` for every SQLite read (honours read-only + pragma policy); read-only stores can dump.
- `orjson` already imported in `persist_sqlite.py`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the base defaults after `BaseWikiStore.dump_edges` — *why*: TASK-4394 calls them on any backend.
2. Add the SQLite natives after `SQLiteWikiStore.dump_edges` — *why*: reference implementation and HelixDB parity oracle.
3. Add `SchemaStore.dump_columns`, then `export_commits` / `import_commits`.
4. Write `test_dump_surface.py`; run it plus the pre-existing suites listed in Validation Commands (AC27 "unchanged").
5. `ruff check --fix` on the four files.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — base defaults)
```python
# occurrences: 1 (verified: grep -c -F '    async def dump_edges(self) -> list[dict[str, Any]]: ...' wiki/store.py)
# AFTER — insert below `    async def dump_edges(self) -> list[dict[str, Any]]: ...` (verified: wiki/store.py:793)

    # -- bulk-transfer surface (FEAT-670 M12; concrete defaults) -----------
    async def dump_attrs(self) -> list[dict[str, Any]]:
        """Return every page attribute as ``{"concept_id", "key", "value"}`` ordered by (concept_id, key).

        Default: derived from :meth:`dump_pages` + :meth:`get_attrs` (empty where attrs are unsupported).
        """
        rows: list[dict[str, Any]] = []
        for page in await self.dump_pages():
            cid = page["concept_id"]
            attrs = await self.get_attrs(cid)
            rows.extend({"concept_id": cid, "key": k, "value": attrs[k]} for k in sorted(attrs))
        rows.sort(key=lambda r: (r["concept_id"], r["key"]))
        return rows

    async def dump_meta(self) -> dict[str, str]:
        """Return every plane-level meta key/value.

        Raises:
            NotImplementedError: When meta is not enumerable on this backend.
        """
        raise NotImplementedError(f"{type(self).__name__}: meta is not enumerable on this backend")

    async def dump_symbols(self) -> list["SymbolRecord"]:
        """Return every native symbol row ordered by concept id.

        Raises:
            NotImplementedError: When the backend has no native symbol store.
        """
        raise NotImplementedError(f"{type(self).__name__}: symbols are not enumerable on this backend")

    async def dump_embeddings(self) -> list[dict[str, Any]]:
        """Return every stored page vector as ``{"concept_id", "vector", "model"}``.

        Raises:
            NotImplementedError: When vectors are not enumerable on this backend.
        """
        raise NotImplementedError(f"{type(self).__name__}: embeddings are not enumerable on this backend")
```
**Why**: concrete defaults keep every existing subclass instantiable; `NotImplementedError` is what TASK-4394 maps to an `unsupported` part (spec §3 M12 `--allow-partial`).

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — SQLite natives)
```python
# occurrences: 1 (verified: grep -c -F '            async with conn.execute("SELECT src, dst, rel FROM edges ORDER BY src, dst, rel") as cur:' wiki/store.py)
# AFTER — insert below the SQLite dump_edges method, i.e. after these verified lines (wiki/store.py:2609-2613):
#     async def dump_edges(self) -> list[dict[str, Any]]:
#         """Return every edge row (bulk export path)."""
#         async with self._read() as conn:
#             async with conn.execute("SELECT src, dst, rel FROM edges ORDER BY src, dst, rel") as cur:
#                 return [dict(row) for row in await cur.fetchall()]

    async def dump_attrs(self) -> list[dict[str, Any]]:
        """Return every ``page_attrs`` row ordered by (concept_id, key); ``[]`` when the table is absent."""
        async with self._read() as conn:
            if not await self._attrs_table_present(conn):
                return []
            async with conn.execute("SELECT concept_id, key, value FROM page_attrs ORDER BY concept_id, key") as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def dump_meta(self) -> dict[str, str]:
        """Return the ``meta`` table as a key-ordered mapping."""
        async with self._read() as conn:
            async with conn.execute("SELECT key, value FROM meta ORDER BY key") as cur:
                return {str(row["key"]): str(row["value"]) for row in await cur.fetchall()}

    async def dump_symbols(self) -> list["SymbolRecord"]:
        """Return every native ``symbols`` row ordered by concept id."""
        async with self._read() as conn:
            async with conn.execute("SELECT * FROM symbols ORDER BY concept_id") as cur:
                return [_row_to_symbol_record(row) for row in await cur.fetchall()]

    async def dump_embeddings(self) -> list[dict[str, Any]]:
        """Return every ``embeddings`` row (vector decoded) ordered by concept id."""
        async with self._read() as conn:
            async with conn.execute("SELECT concept_id, vector, model FROM embeddings ORDER BY concept_id") as cur:
                return [
                    {"concept_id": row["concept_id"], "vector": _unpack_vector(row["vector"]), "model": row["model"]}
                    for row in await cur.fetchall()
                ]
```
**Why**: key-ordered reads make a resumed migration a pure "skip N rows" (spec §3 M12 checkpoint).

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '    async def find_columns(' wiki/schema/store.py)
# BEFORE — insert immediately above `    async def find_columns(` (verified: schema/store.py:135),
#          i.e. after the body of `columns_for` (:126-133)
    async def dump_columns(self) -> list[ColumnRecord]:
        """Return every column row ordered by (table_id, ordinal) — migration bulk read."""
        async with self._read() as conn:
            async with conn.execute("SELECT * FROM columns ORDER BY table_id, ordinal") as cur:
                return [self._column_from_row(row) for row in await cur.fetchall()]

```

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '    async def list_commits(' graphindex/persist_sqlite.py)
# BEFORE — insert immediately above `    async def list_commits(` (verified: persist_sqlite.py:807), after get_commit
    async def export_commits(
        self, ctx: TenantContext, *, after_seq: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Return raw commits with ``seq > after_seq`` (ascending, ≤ ``limit``) incl. payload and items.

        ``seq`` is the ``graph_commits`` rowid; ``prior`` stays JSON text exactly as :meth:`get_commit` returns it.
        Returns ``[]`` (without creating anything) when the tenant database does not exist.
        """
        if not self._db_path(ctx).exists():
            return []
        # FILL IN: SELECT rowid AS seq, * FROM graph_commits WHERE rowid > ? ORDER BY rowid LIMIT ?; decode payload;
        #   attach items (SELECT item_type, item_key, prior … WHERE commit_id = ?) — bounded by "Row contracts"
        raise NotImplementedError

    async def import_commits(
        self, ctx: TenantContext, commits: list[dict[str, Any]], *, replace: bool = False
    ) -> int:
        """Insert raw commit rows preserving ``commit_id`` / ``seq`` / ``reverted_at`` / items.

        Raises:
            ValueError: ``replace=False`` and an incoming commit id exists or an incoming ``seq`` ≤ current max rowid.
        """
        # FILL IN: one transaction via self._connect(ctx); replace ⇒ DELETE both tables; else the append-only checks;
        #   INSERT INTO graph_commits (rowid, commit_id, op, agent_id, run_id, asserted_by, reason, committed_at,
        #   payload, reverted_at) with payload orjson-encoded; executemany items; commit — bounded by "Row contracts"
        raise NotImplementedError

```
**Why**: `rowid = seq` keeps `revert_commit`'s rowid-ordered conflict rule (`:886-893`) valid on imported history.

### `packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py` (CREATE)
See Test Specification.

### FILL IN checklist
- [ ] `export_commits` body — "Row contracts"
- [ ] `import_commits` body — replace / append-only semantics
- [ ] test bodies in `test_dump_surface.py`

---

## Acceptance Criteria

- [ ] **AC-1** (spec AC27) the four `BaseWikiStore` methods, `SchemaStore.dump_columns` and `SQLitePersistence.export_commits` / `import_commits` exist; SQLite natives return key-ordered rows per "Row contracts".
- [ ] **AC-2** (spec `test_dump_bulk_surface_parity`, base half) a minimal `BaseWikiStore` subclass without overrides derives `dump_attrs` and raises `NotImplementedError` for meta / symbols / embeddings.
- [ ] **AC-3** `export_commits` → `import_commits` into a fresh `SQLitePersistence` reproduces `list_commits` / `get_commit` (ids, items, priors, `reverted_at`) and `revert_commit` of an imported, non-reverted commit succeeds; paging with `after_seq` returns every commit exactly once.
- [ ] **AC-4** `import_commits(replace=False)` raises `ValueError` on an existing `commit_id` or a non-increasing `seq`; `replace=True` wipes and imports.
- [ ] **AC-5** every pre-existing test in the Validation Commands list passes unchanged.
- [ ] **AC-6** `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_graph_backends.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.schema import GraphUpdate, NodeKind, UniversalNode
from parrot.knowledge.wiki.schema.models import ColumnRecord
from parrot.knowledge.wiki.schema.store import SchemaStore
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord

BACKENDS = ["sqlite"]  # TASK-4393 appends "helix-memory"


@pytest.fixture(params=BACKENDS)
async def wiki_store(request, tmp_path: Path):
    """A writable wiki store for the requested backend."""
    if request.param == "sqlite":
        yield SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="t")
        return
    raise AssertionError(request.param)


async def _seed(store: BaseWikiStore) -> None:
    """Same fixture plane for every backend: 3 pages (one with attrs), 2 symbols, 2 vectors, 2 meta keys."""
    # FILL IN: upsert_pages, upsert_attrs, upsert_symbols, upsert_embedding, set_meta in non-sorted order


@pytest.mark.asyncio
async def test_dump_rows_key_ordered(wiki_store) -> None: ...          # AC-1


@pytest.mark.asyncio
async def test_base_defaults() -> None: ...                            # AC-2 — minimal subclass implementing only the abstract methods


@pytest.mark.asyncio
async def test_dump_columns_ordered(tmp_path: Path) -> None: ...       # AC-1 — SchemaStore(tmp_path / "schema.db")


def _ctx(tenant: str = "t1") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant
    return ctx


@pytest.mark.asyncio
async def test_export_import_commits_roundtrip(tmp_path: Path) -> None: ...   # AC-3 (incl. after_seq paging + revert on target)


@pytest.mark.asyncio
async def test_import_commits_refusals(tmp_path: Path) -> None: ...           # AC-4


@pytest.mark.asyncio
async def test_export_missing_tenant_is_empty(tmp_path: Path) -> None:
    assert await SQLitePersistence(tmp_path).export_commits(_ctx("nobody")) == []
    assert not (tmp_path / "nobody.db").exists()
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`).
2. Read spec §3 M12 and AC27.
3. No dependencies; confirm the status in `sdd/tasks/index/helixdb-provider.json`.
4. Re-run every `grep -c -F` in "Blueprint anchors" — `wiki/store.py` is also edited by TASK-4392 (registry row); if a count is no longer 1, quote context to disambiguate.
5. Status `in-progress` → commit the index only.
6. Implement; keep the `BACKENDS` list + `wiki_store` fixture shape (TASK-4393 extends them).
7. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. Commit only the listed files; `scripts/sdd/close_task.sh TASK-4391 helixdb-provider verified`.
9. Fill in the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
