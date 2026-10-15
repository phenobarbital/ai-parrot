# TASK-4382: HelixSchemaStore + SchemaPlaneService dispatch

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4377, TASK-4379
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (G3, AC6): the SQL schema overlay plane (`SchemaStore(SQLiteWikiStore)` + a `columns`
side table, FEAT-600) gets a HelixDB twin. `columns` rows become `Column` nodes keyed `(table_id, name)`
with a `COLUMN_OF` edge to the table page; the public surface is identical to `SchemaStore`
(`upsert_columns`, `columns_for`, `find_columns`, `replace_schema_slice`, `fold_ddl_table`).
`SchemaPlaneService.from_root` dispatches on `WikiProjectConfig.backend` (plane-local, outside FEAT-540's
registries). `dump_columns` (bulk read for `wikitoolkit migrate`) is TASK-4393.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py`: `COLUMN_LABEL`,
  `SCHEMA_PLANE`, `HelixSchemaStore(HelixWikiStore)` with the five methods above.
- Modify `wiki/schema/service.py`: `from_root` opens `HelixSchemaStore` (database `schema_<wiki_name>`)
  when `config.backend == "helixdb"`; `from_dir` gains `helix_settings: HelixSettings | None = None`;
  widen the `store` annotations.
- Write `packages/ai-parrot/tests/knowledge/wiki/schema/test_helix_schema_store.py`.

**NOT in scope**: `dump_columns` (TASK-4393); registry rows (TASK-4392); `resolve_helix_params` (TASK-4379);
any change to `schema/store.py`, render / producers / tools.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py` | CREATE | `HelixSchemaStore`, `SCHEMA_PLANE`, `COLUMN_LABEL` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | MODIFY | Backend dispatch in `from_root` / `from_dir` |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_helix_schema_store.py` | CREATE | Column-plane parity + dispatch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.schema.models import ColumnRecord, SchemaPlaneConfig  # verified: wiki/schema/models.py:34, :26
from parrot.knowledge.wiki.schema.store import SchemaStore, _page_source  # verified: wiki/schema/store.py:48, :32
from parrot.knowledge.wiki.schema.service import SchemaPlaneService  # verified: wiki/schema/service.py:46
from parrot.knowledge.wiki.store import WikiPageRecord, SCHEMA_VERSION  # verified: wiki/store.py:433, :51
# Created upstream (not on dev yet):
from parrot.knowledge.wiki.helix_store import HelixWikiStore, WIKI_PLANE  # TASK-4376/4377
from parrot.knowledge.wiki.project import resolve_helix_params  # TASK-4379
from parrot.knowledge.helix.settings import HelixSettings  # TASK-4372
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema  # TASK-4374
from parrot.knowledge.helix import dsl as hdsl  # TASK-4374
from parrot.knowledge.helix.client import _sdk  # TASK-4373 (write_batch()/read_batch())
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py
class SchemaStore(SQLiteWikiStore):                                                    # line 48
    async def upsert_columns(self, columns: list[ColumnRecord]) -> int                 # line 120 — replaces ALL rows of each table_id present
    async def columns_for(self, table_id: str) -> list[ColumnRecord]                   # line 126 — ORDER BY ordinal
    async def find_columns(self, name: Optional[str] = None, fk_target_prefix: Optional[str] = None,
                           limit: int = 50) -> list[ColumnRecord]                      # line 135 — name substring (LIKE %x%),
                                                                                       #   fk prefix, ORDER BY table_id, ordinal
    async def _replace_source_slice_conn(...)                                          # line 159 — NOTE: does NOT drop page_attrs
    async def replace_schema_slice(self, origin: str, pages: list[WikiPageRecord], columns: list[ColumnRecord],
                                   edges: list[tuple[str, str, str, str]]) -> dict[str, Any]   # line 195
        # source_id = f"schema:{origin}"; old table ids = pages(source_id, category='table'); report keys
        #   pages_deleted, pages_written, edges_written, columns_written; 4-tuple edges normalised to 3-tuples
    async def fold_ddl_table(self, page: WikiPageRecord, columns: list[ColumnRecord],
                             edges: list[tuple[str, str, str, str]], *, changed_only: bool = False
                             ) -> Literal["created", "updated", "unchanged"]          # line 226
        # existing page whose _page_source != "ddl" ⇒ only add "defined_in" edges, "unchanged";
        # changed_only and same content_hash ⇒ "unchanged"; else upsert page + replace columns + edges
def _page_source(page: dict[str, Any]) -> str                                          # line 32
# packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py
class ColumnRecord(BaseModel):   # line 34 — table_id, ordinal, name, data_type, nullable, default, comment, is_primary_key, fk_target
# packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py
class SchemaPlaneService:                                                              # line 46
    def __init__(self, store: SchemaStore, config: SchemaPlaneConfig, plane_dir: Path, shared_root: Optional[Path]) -> None  # line 49
    def from_root(cls, root: Optional[Path] = None) -> "SchemaPlaneService"           # line 60 (store built :66-68)
    def from_dir(cls, plane_dir: Path, *, config: Optional[SchemaPlaneConfig] = None, read_only: bool = True)  # line 72 (store :82)
    def store(self) -> SchemaStore                                                     # property line 86
# service uses on the store: add_edges, columns_for, find_columns, fold_ddl_table, get_page, list_pages, neighbors,
#   page_hashes, replace_schema_slice, search_fts, upsert_columns, upsert_pages — all present on HelixSchemaStore
```

### Verified anchors (MODIFY `schema/service.py`)
| Anchor (verbatim) | `grep -c -F` | Context |
|---|---|---|
| `        store = SchemaStore(` | 2 | line 66 (from_root, multi-line: next line `            plane_dir / "schema.db", wiki_name="schema", sqlite_policy=sqlite_policy_from_config(config)`) and line 82 (from_dir) |
| `        store = SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=read_only)` | 1 | line 82 |

### Does NOT Exist
- ~~`parrot.knowledge.wiki.schema.helix_store`~~ — created here.
- ~~`SchemaStore.dump_columns`~~ — TASK-4391/4393.
- ~~A HelixDB LIKE / substring predicate~~ — not in the wheel-verified DSL; substring/prefix filters run client-side after an equality / label scan.
- ~~Schema-plane rows in FEAT-540 registries~~ — plane-local dispatch.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_helix_schema_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore.replace_schema_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore.fold_ddl_table",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#_page_source",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py#ColumnRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py#SchemaPlaneService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py#SchemaPlaneService.from_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py#SchemaPlaneService.from_dir"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `Column` node: unique `column_key = f"{table_id}\x1f{name}"`; equality `table_id`, `name`, `fk_target`;
  props = every `ColumnRecord` field (`model_dump()` names, e.g. `default`, not the SQLite column name `dflt`). A `COLUMN_OF` edge
  links each Column to `Page(table_id)` (stub endpoint allowed, TASK-4376 rule).
- `SCHEMA_PLANE = PlaneSchema(plane="schema", schema_version=SCHEMA_VERSION, labels=[*WIKI_PLANE.labels, COLUMN_LABEL], edge_labels=["*"])`;
  `HelixSchemaStore.plane_schema = SCHEMA_PLANE`; default `wiki_name="schema"`.
- **One write batch per public write.** `replace_schema_slice`: one read batch (old table ids of
  `schema:{origin}` + preserved incoming edges, same rule as TASK-4376's `replace_source_slice`), then one write
  batch that drops the old slice pages, drops Column nodes of `old_table_ids | new_table_ids`, writes pages,
  edges (normalised 3-tuples), preserved edges and the new Columns. Parity note: SQLite's schema slice does
  **not** drop `page_attrs` (`schema/store.py:159-193`); dropping the Page node on HelixDB removes its attrs —
  schema pages carry no attrs today, so this is accepted; record it in the Completion Note.
- `fold_ddl_table`: read the existing page (body + content_hash) then branch exactly like SQLite; the
  read-then-write is two round trips (SQLite holds one immediate transaction). Close the race with a
  conditional entry: write only if the stored `content_hash` still equals the one read (reuse
  `hdsl.cas_page_entries`); on a lost race re-read once and re-decide.
- Reuse TASK-4376 internals (`_add_page_entries`, `_add_edge_entries`, `_c`, `_assert_writable`) — do not
  re-implement page/edge writing.

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-4376/4377 helper names and TASK-4379's `resolve_helix_params` signature.
2. Write `schema/helix_store.py`; then the service dispatch; then tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py` (CREATE)
```python
"""HelixDB SQL-schema overlay plane (FEAT-670 M6): Column nodes + COLUMN_OF edges."""
from __future__ import annotations

from typing import Any, Literal, Optional

from parrot.knowledge.helix import dsl as hdsl
from parrot.knowledge.helix.client import _sdk
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema
from parrot.knowledge.helix.settings import HelixSettings
from parrot.knowledge.wiki.helix_store import WIKI_PLANE, HelixWikiStore
from parrot.knowledge.wiki.schema.models import ColumnRecord
from parrot.knowledge.wiki.schema.store import _page_source
from parrot.knowledge.wiki.store import SCHEMA_VERSION, WikiPageRecord

COLUMN_REL = "COLUMN_OF"
COLUMN_LABEL = LabelSpec(label="Column", unique_key="column_key", equality=["table_id", "name", "fk_target"])
SCHEMA_PLANE = PlaneSchema(plane="schema", schema_version=SCHEMA_VERSION, labels=[*WIKI_PLANE.labels, COLUMN_LABEL],
                           edge_labels=["*"])


def column_key(table_id: str, name: str) -> str:
    """Unique Column key (mirrors SQLite PRIMARY KEY (table_id, name))."""
    return f"{table_id}\x1f{name}"


def _column_props(column: ColumnRecord) -> dict[str, Any]:
    props = column.model_dump()
    props["column_key"] = column_key(column.table_id, column.name)
    return props


def _column_from_props(props: dict[str, Any]) -> ColumnRecord:
    return ColumnRecord(**{k: v for k, v in props.items() if k in ColumnRecord.model_fields})


class HelixSchemaStore(HelixWikiStore):
    """Schema overlay plane on HelixDB; same public surface as SchemaStore."""

    plane_schema = SCHEMA_PLANE

    def __init__(self, settings: HelixSettings, wiki_name: str = "schema", *, read_only: bool = False) -> None:
        super().__init__(settings, wiki_name=wiki_name, read_only=read_only)

    def _add_column_entries(self, batch: Any, columns: list[ColumnRecord], drop_table_ids: set[str]) -> None:
        """Drop all Columns of `drop_table_ids`, then upsert `columns` + COLUMN_OF edges (same batch)."""
        # FILL IN: drop Column where table_id ∈ drop_table_ids; upsert_node_entries("Column", "column_key", _column_props(c));
        #          COLUMN_OF edge Column → Page(table_id) via TASK-4376's edge helper semantics — bounded by spec §3 M6
        raise NotImplementedError

    async def upsert_columns(self, columns: list[ColumnRecord]) -> int:
        """Replace all Column rows of each table id present in `columns`."""
        self._assert_writable()
        client = await self._c()
        batch = _sdk().write_batch()
        self._add_column_entries(batch, columns, {c.table_id for c in columns})
        await client.write(batch, query_name="schema.upsert_columns")
        return len(columns)

    async def columns_for(self, table_id: str) -> list[ColumnRecord]:
        """Columns of one table ordered by ordinal."""
        raise NotImplementedError  # FILL IN: equality on table_id, sort ordinal

    async def find_columns(self, name: Optional[str] = None, fk_target_prefix: Optional[str] = None,
                           limit: int = 50) -> list[ColumnRecord]:
        """Name substring and/or fk_target prefix; ordered by (table_id, ordinal)."""
        raise NotImplementedError  # FILL IN: label scan, client-side `name in col.name` / fk startswith, sort, limit

    async def replace_schema_slice(self, origin: str, pages: list[WikiPageRecord], columns: list[ColumnRecord],
                                   edges: list[tuple[str, str, str, str]]) -> dict[str, Any]:
        """Replace schema pages, edges and columns atomically (one write batch)."""
        self._assert_writable()
        source_id = f"schema:{origin}"
        normalized = [(src, dst, rel) for src, dst, rel, _prov in edges]
        new_table_ids = {p.concept_id for p in pages if p.category == "table"}
        # FILL IN: one read batch → old_ids (pages of source_id), old_table_ids (category == "table"), preserved edges;
        #          one write batch → drop old slice + its symbols, _add_page_entries, _add_edge_entries(normalized + preserved),
        #          _add_column_entries(columns, old_table_ids | new_table_ids)
        old_ids: list[str] = []
        return {"pages_deleted": len(old_ids), "pages_written": len(pages), "edges_written": len(normalized),
                "columns_written": len(columns)}

    async def fold_ddl_table(self, page: WikiPageRecord, columns: list[ColumnRecord],
                             edges: list[tuple[str, str, str, str]], *, changed_only: bool = False
                             ) -> Literal["created", "updated", "unchanged"]:
        """Fold one DDL-derived table page, never overwriting a live page."""
        self._assert_writable()
        normalized = [(src, dst, rel) for src, dst, rel, _prov in edges]
        existing = await self.get_page(page.concept_id, include_body=True)
        if existing is not None and _page_source(existing) != "ddl":
            await self.add_edges([e for e in normalized if e[2] == "defined_in"])
            return "unchanged"
        if changed_only and existing is not None and existing.get("content_hash") == page.content_hash:
            return "unchanged"
        # FILL IN: ONE conditional batch (hdsl.cas_page_entries on existing content_hash, or insert-only when absent):
        #          page + _add_column_entries(columns, {page.concept_id}) + edges; on a lost race re-read once — bounded by
        #          schema/store.py:226-266 semantics
        return "updated" if existing is not None else "created"
```
**Why this shape**: identical method surface lets `SchemaPlaneService` (and its tools / MCP mount) work
unchanged; reusing `_page_source` keeps the "never overwrite a live page" rule in one place.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` (MODIFY)
```python
# occurrences: 2 of `        store = SchemaStore(` — this one is from_root (line 66), disambiguated by its next line
#   `            plane_dir / "schema.db", wiki_name="schema", sqlite_policy=sqlite_policy_from_config(config)`
# REPLACE lines 66-68 with:
        if config.backend == "helixdb":
            from parrot.knowledge.wiki.project import resolve_helix_params
            from parrot.knowledge.wiki.schema.helix_store import HelixSchemaStore

            settings = resolve_helix_params(config, root=shared_root).with_database(f"schema_{config.wiki_name}")
            store: "SchemaStore | HelixSchemaStore" = HelixSchemaStore(settings)
        else:
            store = SchemaStore(
                plane_dir / "schema.db", wiki_name="schema", sqlite_policy=sqlite_policy_from_config(config)
            )
```
```python
# occurrences: 1 (verified: grep -c -F '        store = SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=read_only)')
# from_dir (line 72) gains `helix_settings: "HelixSettings | None" = None`; REPLACE line 82 with:
        if helix_settings is not None:
            from parrot.knowledge.wiki.schema.helix_store import HelixSchemaStore

            store: "SchemaStore | HelixSchemaStore" = HelixSchemaStore(helix_settings, read_only=read_only)
        else:
            store = SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=read_only)
```
**Why**: plane-local dispatch per spec §2; lazy imports keep SQLite users free of `parrot.knowledge.helix`.
Widen `__init__`'s `store` and the `store` property's return annotation to `"SchemaStore | HelixSchemaStore"`
(TYPE_CHECKING imports of `HelixSchemaStore` and `HelixSettings`).

### FILL IN checklist
- [ ] `_add_column_entries`, `columns_for`, `find_columns`
- [ ] `replace_schema_slice` read + write batches
- [ ] `fold_ddl_table` conditional write + one re-read on a lost race

---

## Acceptance Criteria

- [ ] AC6: `HelixSchemaStore` passes `upsert_columns` / `columns_for` / `find_columns` / `replace_schema_slice` / `fold_ddl_table` parity cases on embedded InMemory (`test_helix_schema_store_columns`).
- [ ] `SchemaPlaneService.from_root` with `backend: helixdb` builds a `HelixSchemaStore` on database `schema_<wiki_name>`; SQLite path unchanged (existing `packages/ai-parrot/tests/knowledge/wiki/schema/test_service.py` passes).
- [ ] `ruff check` clean on both source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_helix_schema_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_service.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_helix_schema_store.py
import uuid

import pytest

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")
from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.wiki.schema.helix_store import HelixSchemaStore
from parrot.knowledge.wiki.schema.models import ColumnRecord
from parrot.knowledge.wiki.schema.store import SchemaStore


@pytest.fixture(params=["sqlite", "helix-memory"])
async def schema_store(request, tmp_path):
    if request.param == "sqlite":
        yield SchemaStore(tmp_path / "schema.db")
        return
    store = HelixSchemaStore(HelixSettings(mode=HelixMode.MEMORY, database=f"schema_{uuid.uuid4().hex}"))
    await store.initialize()
    yield store
    await store.close()


async def test_helix_schema_store_columns(schema_store): ...        # upsert replaces per table; columns_for ordinal order
async def test_find_columns_substring_and_fk_prefix(schema_store): ...
async def test_replace_schema_slice_report_and_columns(schema_store): ...   # report keys; stale tables' columns gone
async def test_fold_ddl_never_overwrites_live_page(schema_store): ...       # live page ⇒ "unchanged" + defined_in edge only
async def test_fold_ddl_changed_only(schema_store): ...
async def test_service_from_root_dispatches_helix(tmp_path, monkeypatch): ...  # monkeypatch schema.service.load_effective_config
                                                                                # (WikiProjectConfig.model_construct(backend="helixdb", …)) and
                                                                                # resolve_helix_params → memory settings
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`)
2. **Read the spec** (§3 M6)
3. **Check dependencies** — TASK-4377, TASK-4379 must be `"done"`
4. **Verify the Codebase Contract** — re-run both `grep -c -F` anchors
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**; no `NotImplementedError` may remain
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4382 helixdb-provider verified`
10. **Fill in the Completion Note**, commit the SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
