# TASK-4394: `wiki/migrate.py` — cross-backend plane copy engine

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 12, §2 "Migration", §7 "Migrate copies through contracts only", AC26, AC27)
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4393, TASK-4392
**Assigned-to**: unassigned

---

## Context

Resolved §8 Q2: `wikitoolkit migrate --to <backend>` copies one plane between any two registered backends, for
planes whose canonical sources are gone (curated pages, agent-written GraphIndex memory) and as the rollback path
(`--to sqlite`). This task is the **engine** (`wiki/migrate.py`): part loops, resumable checkpoint, verification
report. The CLI command is TASK-4395. Every read is a bulk-read call (`dump_*`, `list_sources`, `load_graph`,
`export_commits`) and every write a public write-surface call — **no backend-specific SQL / AQL / DSL here**.

The bulk-read surface exists after TASK-4391 (SQLite natives + base defaults) and TASK-4393 (HelixDB natives);
`"helixdb"` is a registered name after TASK-4392.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/migrate.py` with: `GraphHistoryTransfer` (runtime-checkable
  Protocol), `MigrationPart`, `MigrationCheckpoint` (+ `load` / `save`), `PartReport`, `MigrationReport`,
  `MigrationRefused`, `migrate_wiki_plane`, `migrate_schema_plane`, `migrate_graphindex`, `verify_copy`,
  `open_schema_store` (backend-name → schema store, used by the CLI).
- Tests in `tests/knowledge/wiki/test_migrate.py` (sqlite → helix-memory and sqlite → sqlite).

**NOT in scope**: the click command, exit codes and report printing (TASK-4395); the bulk-read methods themselves
(TASK-4391/4393); the ledger (refused by the CLI); PageIndex/BookStore (re-project); live tests (TASK-4397).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/migrate.py` | CREATE | migration engine |
| `packages/ai-parrot/tests/knowledge/wiki/test_migrate.py` | CREATE | engine tests |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord   # wiki/store.py:697, :433
from parrot.knowledge.wiki.symbols import SymbolRecord                  # wiki/symbols.py:58
from parrot.knowledge.wiki.schema.store import SchemaStore              # wiki/schema/store.py:48
from parrot.knowledge.wiki.schema.models import ColumnRecord            # wiki/schema/models.py:34
from parrot.knowledge.wiki.sources_backend import SourceManifestBackend # wiki/sources_backend.py:50 (SYNC protocol)
from parrot.knowledge.graphindex.protocols import GraphPersistence      # graphindex/protocols.py:103
from parrot.knowledge.wiki.project import WikiProjectConfig, PARROT_DIR, sqlite_policy_from_config  # project.py:574, :45, :984
# created by dependency tasks (verify before use):
#   BaseWikiStore.dump_attrs / dump_meta / dump_symbols / dump_embeddings   (TASK-4391; Helix natives TASK-4393)
#   SchemaStore.dump_columns                                               (TASK-4391; HelixSchemaStore TASK-4393)
#   SQLitePersistence.export_commits / import_commits                      (TASK-4391; HelixPersistence TASK-4393)
from parrot.knowledge.wiki.schema.helix_store import HelixSchemaStore      # TASK-4382 (HelixWikiStore subclass, ctor (settings, wiki_name=...))
from parrot.knowledge.wiki.project import resolve_helix_params             # TASK-4379
```

### Existing Signatures to Use
```python
# wiki/store.py — BaseWikiStore
async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                 # :744 (abstract) — REPLACES page attrs (attrs={} clears)
async def add_edges(self, edges: list[tuple]) -> int                             # :747 — (src, dst, rel) or (src, dst, rel, provenance)
async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None   # :761
async def dump_pages(self) -> list[dict[str, Any]]                               # :790 (abstract)
async def dump_edges(self) -> list[dict[str, Any]]                               # :793 (abstract)
async def stats(self) -> dict[str, Any]                                          # :796 — SQLite keys: pages, edges, sources, embeddings, symbols, total_tokens, categories, attrs_pages (:2615)
async def broken_edges(self) -> list[dict[str, Any]]                             # :803
async def index_drift(self) -> dict[str, int]                                    # :815
async def missing_bodies(self) -> list[str]                                      # :820
async def set_meta(self, key: str, value: str) -> None                           # :872
async def upsert_attrs(self, concept_id, attrs, *, replace: bool = True) -> int  # :734
async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int   # :958
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]] # :1074
# SQLiteWikiStore.dump_pages (:2595) columns: concept_id, node_id, title, category, summary, body, source_id,
#   token_count, created_at, updated_at, content_hash — NO origin / asserted_by
# SQLiteWikiStore.dump_edges (:2609) columns: src, dst, rel — NO provenance

# wiki/schema/store.py
async def upsert_columns(self, columns: list[ColumnRecord]) -> int   # :120 — REPLACES all rows of every table_id present
async def columns_for(self, table_id: str) -> list[ColumnRecord]     # :126

# wiki/project.py
def schema_path(self, root: Path) -> Path                            # :750 — <root>/.parrot/schema
def graph_path(self, root: Path) -> Path                             # :734

# graphindex/protocols.py — GraphPersistence: persist_graph(ctx, nodes, edges), load_graph(ctx),
#   get_commit(ctx, id), list_commits(ctx, *, run_id=None, agent_id=None, limit=50), close()   # :125-152
```

### Does NOT Exist
- ~~`wiki/migrate.py`, `GraphHistoryTransfer`, `MigrationReport`, `MigrationCheckpoint`~~ — created here.
- ~~`SourceCollectionManager.upsert_many`~~ — the manager has no such public method; migrate works on a `SourceManifestBackend` (sync) passed in by the caller.
- ~~An async `SourceManifestBackend`~~ — the registry contract is sync; call it through `asyncio.to_thread`.
- ~~A schema-plane backend registry~~ — `open_schema_store` is the single name→store mapping (sqlite, helixdb).
- ~~`origin` / `asserted_by` in SQLite `dump_pages`, `provenance` in SQLite `dump_edges`, `source_id` on `SymbolRecord`~~ — see drift.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/migrate.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_migrate.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.page_hashes",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore.upsert_columns",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py#ColumnRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py#SourceManifestBackend",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py#GraphPersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord"
  ]
}
```

---

## Implementation Notes

### Spec drift / fidelity gaps found while writing this task (record in the Completion Note; open ledger issues)
1. SQLite `dump_pages` omits `origin` / `asserted_by` and `dump_edges` omits `provenance`, so a copy resets them to
   `"ingest"` / `None` / `"extracted"`. `page_hashes` (content_hash) still verifies. Map what the row carries; when a
   key is present (HelixDB natives may carry it) pass it through. Fixing the SQLite dumps is TASK-4391's surface, not
   this task — open `wikitoolkit ledger open --kind feature_gap --severity minor --discovered-from spec:FEAT-670 …`.
2. `SymbolRecord` has no `source_id`; `upsert_symbols(batch)` is called with `source_id=None`. Same ledger treatment.
3. `upsert_columns` **replaces every row of each `table_id` present** — column batches must never split a table:
   group `dump_columns()` by `table_id` and cut batches at table boundaries (a table larger than `batch_size` is one batch).
4. `upsert_pages` replaces a page's attrs (`attrs={}` clears them) — parts must run in the fixed order
   `pages → edges → attrs → …`; never re-run `pages` after `attrs` on resume without re-running `attrs`.
5. Spec signatures pass no backend names; `MigrationReport.source/target` come from `checkpoint.source_backend /
   target_backend` when a checkpoint is given, else `type(store).__name__`.

### Decided behaviour
- **Parts**: wiki = `pages, edges, attrs, symbols, meta, embeddings, sources`; schema = wiki parts + `columns`;
  graphindex = `graph`, `commits`.
- **Batching / resume**: reads are key-ordered; `checkpoint.written[part] = N` ⇒ skip the first N rows; after every
  batch `written[part] += len(batch)` and `checkpoint.save()`.
- **Fingerprint**: `sha256(json.dumps(await source.stats(), sort_keys=True, default=str))`; a checkpoint whose
  fingerprint differs ⇒ `MigrationRefused("stale checkpoint")` before any write.
- **Emptiness**: target non-empty (`stats()["pages"] or stats()["edges"]`; GraphIndex: `list_commits(ctx, limit=1)`
  or `load_graph` non-empty) and not `replace` and not resuming ⇒ `MigrationRefused` before any write.
- **Unsupported**: a `dump_*` raising `NotImplementedError` ⇒ `PartReport(status="unsupported")`; `ok` is False
  unless `allow_partial`. Commits require both sides `isinstance(x, GraphHistoryTransfer)`.
- **dry_run**: counts only (`source_count`), no writes, no checkpoint; `status="skipped"`.
- **Verification**: `verify_copy` — `sample` evenly spaced concept ids from `dump_pages()`; mismatching
  `page_hashes` ⇒ `sample_hash_mismatches`; target lint = `broken_edges` count, `missing_bodies` count, `index_drift`.
  `ok = all parts copied|skipped (or unsupported with allow_partial) and not mismatches and target_count >= written`.
- **Sources**: `asyncio.to_thread(src.list_sources)` → batches → `asyncio.to_thread(dst.upsert_many, batch)`.

### Key Constraints
- No import of `aiosqlite`, `helixdb`, or any backend module at top level — the only backend-aware code is
  `open_schema_store`, which imports lazily.
- Pydantic v2 models; `logging.getLogger(__name__)`; Google docstrings.

---

## Implementation Blueprint

### Steps (in order)
1. Models + checkpoint I/O. 2. `_copy_part` generic loop. 3. Three `migrate_*` drivers. 4. `verify_copy`. 5. Tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/migrate.py` (CREATE)
```python
"""Cross-backend plane copy for ``wikitoolkit migrate`` (FEAT-670 M12, resolved Q2).

Copies one plane through the backend contracts only: bulk reads (``dump_*``, ``list_sources``, ``load_graph``,
``export_commits``) and the public write surface. Resumable via a checkpoint, verified by a report.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord

logger = logging.getLogger(__name__)


class MigrationRefused(RuntimeError):
    """Raised before any write when a migration must not start (non-empty target, stale checkpoint)."""


@runtime_checkable
class GraphHistoryTransfer(Protocol):
    """Capability ``history``: raw commit export/import (SQLite + HelixDB persistence)."""

    async def export_commits(self, ctx: Any, *, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]: ...
    async def import_commits(self, ctx: Any, commits: list[dict[str, Any]], *, replace: bool = False) -> int: ...


class MigrationPart(str, Enum):
    PAGES = "pages"
    EDGES = "edges"
    ATTRS = "attrs"
    SYMBOLS = "symbols"
    META = "meta"
    EMBEDDINGS = "embeddings"
    SOURCES = "sources"
    COLUMNS = "columns"
    GRAPH = "graph"
    COMMITS = "commits"


WIKI_PARTS: tuple[MigrationPart, ...] = (
    MigrationPart.PAGES, MigrationPart.EDGES, MigrationPart.ATTRS, MigrationPart.SYMBOLS,
    MigrationPart.META, MigrationPart.EMBEDDINGS, MigrationPart.SOURCES,
)


class MigrationCheckpoint(BaseModel):
    """``<root>/.parrot/migrate/<plane>.<from>-<to>.json`` — written after every batch."""

    plane: str
    source_backend: str
    target_backend: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    batch_size: int = 500
    fingerprint: str = ""
    written: dict[str, int] = Field(default_factory=dict)
    path: Optional[Path] = Field(default=None, exclude=True)

    @classmethod
    def load(cls, path: Path) -> "MigrationCheckpoint":
        """Read a checkpoint file; ``path`` is kept for later saves."""
        cp = cls.model_validate_json(path.read_text(encoding="utf-8"))
        cp.path = path
        return cp

    def save(self) -> None:
        """Atomically rewrite the checkpoint file (no-op without ``path``)."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)


class PartReport(BaseModel):
    part: str
    status: Literal["copied", "skipped", "unsupported", "failed"]
    source_count: int = 0
    written: int = 0
    target_count: int = 0
    detail: str = ""


class MigrationReport(BaseModel):
    plane: str
    source: str
    target: str
    dry_run: bool
    duration_s: float
    parts: list[PartReport]
    sample_hash_mismatches: list[str] = Field(default_factory=list)
    target_lint: dict[str, Any] = Field(default_factory=dict)
    ok: bool


async def stats_fingerprint(store: Any) -> str:
    """sha256 of the source ``stats()`` JSON (resume guard)."""
    payload = json.dumps(await store.stats(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _copy_part(
    part: MigrationPart,
    rows: Sequence[Any],
    write: Callable[[list[Any]], Awaitable[Any]],
    *,
    batch_size: int,
    checkpoint: Optional[MigrationCheckpoint],
    dry_run: bool,
    batches: Optional[list[list[Any]]] = None,
) -> PartReport:
    """Skip already-written rows, write the rest in batches, checkpoint after each batch."""
    done = checkpoint.written.get(part.value, 0) if checkpoint else 0
    if dry_run:
        return PartReport(part=part.value, status="skipped", source_count=len(rows), detail="dry-run")
    # FILL IN: when `batches` is given (columns grouped by table) iterate them, skipping whole batches whose
    #   cumulative row count ≤ done; else slice rows[done:] into batch_size chunks; await write(batch);
    #   bump checkpoint.written[part] and checkpoint.save() after EVERY batch; return PartReport(status="copied",
    #   source_count=len(rows), written=done+new) — bounded by AC26 "resumes without duplicates"
    raise NotImplementedError


def _page_record(row: dict[str, Any]) -> WikiPageRecord:
    """Map a ``dump_pages`` row to a write record (keys absent from the row keep model defaults — drift 1)."""
    fields = WikiPageRecord.model_fields
    return WikiPageRecord(**{k: v for k, v in row.items() if k in fields and k != "attrs" and v is not None})


async def migrate_wiki_plane(
    source: BaseWikiStore,
    target: BaseWikiStore,
    *,
    batch_size: int = 500,
    checkpoint: Optional[MigrationCheckpoint] = None,
    replace: bool = False,
    allow_partial: bool = False,
    sample: int = 50,
    dry_run: bool = False,
    sources: Optional[tuple[Any, Any]] = None,
    extra_parts: Sequence[tuple[MigrationPart, Callable[[], Awaitable[list[Any]]], Callable[[list[Any]], Awaitable[Any]]]] = (),
) -> MigrationReport:
    """Copy pages, edges, attrs, symbols, meta, embeddings and sources (in that order).

    Raises:
        MigrationRefused: Non-empty target without ``replace`` (and not resuming), or a stale checkpoint.
    """
    started = time.monotonic()
    # FILL IN: refusal checks (fingerprint vs checkpoint; target emptiness unless replace or checkpoint.written);
    #   for each part in WIKI_PARTS: read via dump_pages→_page_record / dump_edges→tuples (with provenance if present) /
    #   dump_attrs→group by concept_id→upsert_attrs(replace=True) / dump_symbols→upsert_symbols / dump_meta→set_meta /
    #   dump_embeddings→upsert_embedding / sources→to_thread(list_sources, upsert_many) (status "skipped" when sources is None);
    #   NotImplementedError from a dump → PartReport(status="unsupported"); any other exception → status "failed" + re-raise
    #   after saving the checkpoint; then extra_parts (schema columns); then verify_copy; compute ok — bounded by AC26/AC27
    raise NotImplementedError


async def migrate_schema_plane(source: Any, target: Any, **kwargs: Any) -> MigrationReport:
    """Wiki parts + ``columns`` (``upsert_columns`` batches cut at ``table_id`` boundaries — drift 3)."""

    async def read_columns() -> list[Any]:
        return list(await source.dump_columns())

    async def write_columns(batch: list[Any]) -> Any:
        return await target.upsert_columns(batch)

    report = await migrate_wiki_plane(
        source, target, extra_parts=((MigrationPart.COLUMNS, read_columns, write_columns),), **kwargs
    )
    report.plane = "schema"
    return report


async def migrate_graphindex(
    source: Any,
    target: Any,
    ctx: Any,
    *,
    with_history: bool = True,
    batch_size: int = 500,
    checkpoint: Optional[MigrationCheckpoint] = None,
    replace: bool = False,
    allow_partial: bool = False,
    dry_run: bool = False,
    **_: Any,
) -> MigrationReport:
    """``graph`` = load_graph → persist_graph (one call); ``commits`` = export_commits pages → import_commits."""
    # FILL IN: emptiness = load_graph(target) nodes or list_commits(target, limit=1); history requires
    #   isinstance(source, GraphHistoryTransfer) and isinstance(target, GraphHistoryTransfer) else "unsupported";
    #   page export_commits(after_seq=last_seq, limit=batch_size) until empty, import_commits(batch, replace=replace and first batch);
    #   target_count via len(list_commits(target, limit=10**6)) — bounded by AC26, test_migrate_graphindex_with_history
    raise NotImplementedError


async def verify_copy(source: BaseWikiStore, target: BaseWikiStore, *, sample: int) -> tuple[list[str], dict[str, Any]]:
    """Sampled ``page_hashes`` parity + target lint (``broken_edges`` / ``missing_bodies`` / ``index_drift``)."""
    ids = [row["concept_id"] for row in await source.dump_pages()]
    step = max(1, len(ids) // max(1, sample))
    picked = ids[::step][:sample]
    src_hashes = await source.page_hashes(picked)
    dst_hashes = await target.page_hashes(picked)
    mismatches = [cid for cid in picked if src_hashes.get(cid) != dst_hashes.get(cid)]
    lint = {
        "broken_edges": len(await target.broken_edges()),
        "missing_bodies": len(await target.missing_bodies()),
        "index_drift": await target.index_drift(),
    }
    return mismatches, lint


def open_schema_store(backend: str, root: Path, config: Any, *, read_only: bool = False) -> Any:
    """Open the schema plane of ``backend`` for ``config`` (the only backend-name mapping in this module)."""
    if backend == "sqlite":
        from parrot.knowledge.wiki.project import sqlite_policy_from_config
        from parrot.knowledge.wiki.schema.store import SchemaStore

        plane_dir = config.schema_path(root)
        plane_dir.mkdir(parents=True, exist_ok=True)
        return SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=read_only,
                           sqlite_policy=sqlite_policy_from_config(config))
    if backend == "helixdb":
        from parrot.knowledge.wiki.project import resolve_helix_params
        from parrot.knowledge.wiki.schema.helix_store import HelixSchemaStore

        settings = resolve_helix_params(config, root=root).with_database(f"schema_{config.wiki_name}")
        return HelixSchemaStore(settings, wiki_name="schema", read_only=read_only)
    raise ValueError(f"schema plane has no {backend!r} backend (expected 'sqlite' or 'helixdb')")
```
**Why this shape**: spec §3 M12 skeleton verbatim (models, function names, kwargs), plus `MigrationRefused`,
`stats_fingerprint`, `open_schema_store` and `extra_parts` so the schema driver reuses the wiki loop instead of
duplicating it. `SchemaStore.__init__(db_path, wiki_name="schema", *, read_only=False, sqlite_policy=None,
persistent_writer=False)` (verified `schema/store.py:53-61`) accepts both keywords together.

### FILL IN checklist
- [ ] `_copy_part` — resume skip + per-batch checkpoint; bounded by AC26.
- [ ] `migrate_wiki_plane` — refusals, part loop, unsupported/failed handling, verification, `ok`; bounded by AC26/AC27.
- [ ] `migrate_graphindex` — graph + commit history; bounded by AC26.

---

## Acceptance Criteria

- [ ] AC26 (engine half): checkpoint written after every batch; resume skips written rows (no duplicates); stale fingerprint refused; non-empty target refused before any write without `replace`; report carries per-part source / written / target counts, sampled hash parity and target lint.
- [ ] AC27 (consumer half): `GraphHistoryTransfer` is a `runtime_checkable` Protocol; commits copy preserves `commit_id`, `seq`, items, `reverted_at`.
- [ ] `migrate.py` imports no backend module at top level and contains no SQL / AQL / DSL text.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_migrate.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_migrate.py
"""FEAT-670 M12 engine — sqlite→helix-memory and sqlite→sqlite copies."""
import pytest

from parrot.knowledge.wiki.migrate import (
    GraphHistoryTransfer, MigrationCheckpoint, MigrationRefused, migrate_graphindex, migrate_wiki_plane, verify_copy,
)

# helix-memory tests: pytest.importorskip("helixdb_uniffi") inside the test / fixture (not at module top) so the
# sqlite→sqlite cases still run without the wheel.


async def test_migrate_wiki_plane_sqlite_to_helix_memory(tmp_path):
    """Seed pages/edges/attrs/symbols/meta/embeddings on SQLiteWikiStore → every part copied, ok, stats equal, hashes equal, lint clean."""


async def test_migrate_checkpoint_resume(tmp_path):
    """Inject a failure in the 2nd pages batch (batch_size=2) → checkpoint has written['pages']==2; resume → no duplicates, ok;
    mutate the source then resume → MigrationRefused (stale fingerprint)."""


async def test_migrate_refuses_non_empty_target(tmp_path):
    """Target with one page and replace=False → MigrationRefused, target unchanged."""


async def test_migrate_unsupported_part_needs_allow_partial(tmp_path):
    """A source whose dump_meta raises NotImplementedError → PartReport 'unsupported', ok False; allow_partial=True → ok True."""


async def test_migrate_graphindex_with_history(tmp_path):
    """SQLitePersistence → SQLitePersistence (and helix-memory): graph equal; list_commits / get_commit equal (ids, seq, items,
    reverted_at); revert_commit of a copied commit works on the target."""


async def test_migrate_report_detects_mismatch(tmp_path):
    """Mutate a target page between copy and verify_copy → sample_hash_mismatches non-empty."""


def test_graph_history_transfer_is_runtime_checkable():
    from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
    assert issubclass(SQLitePersistence, GraphHistoryTransfer)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`
2. **Read the spec** §3 M12 and §7 "Migrate copies through contracts only".
3. **Check dependencies** — TASK-4393 and TASK-4392 `done` (which implies 4391, 4377, 4382, 4384); read the real
   `dump_*` / `export_commits` signatures they shipped before coding — they are this task's contract.
4. **Verify the Codebase Contract**.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — only the two listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4394 helixdb-provider verified`.
10. **Fill in the Completion Note** (drift items 1–2 with their ledger ids), then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
