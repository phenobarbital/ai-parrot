# TASK-3684: `SchemaPlaneService`: from_root/from_dir, sync, lookup, neighbors, search, `SchemaPlaneReader`

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3680, TASK-3681, TASK-3682, TASK-3683
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (service half). The application-facing service mirrors `LedgerService.from_root` (ledger/service.py:116-143) and adds a rootless `from_dir` (brainstorm decision; FEAT-569 alignment). It owns the read API the tools/CLI/CachePartition use and the `sync` write path. `SchemaPlaneReader` is the Protocol `bots/database` types against.

---

## Scope

- Create `schema/service.py` — `SchemaPlaneReader` Protocol, `SchemaPlaneService` with `from_root`, `from_dir`, `store`, `sync`, `lookup`, `neighbors`, `search`, `sources`, and the reader methods `get_table`/`put_table`/`list_tables`.
- Write `test_service.py` (own `schema_service` fixture; do not edit conftest).

**NOT in scope**: `ingest_ddl` / `diff` (TASK-3686 extends this file), CLI (TASK-3687), tools (TASK-3689), MCP mount (TASK-3690).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | CREATE | service + reader protocol |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_service.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.knowledge.wiki.project import find_shared_root, load_effective_config, sqlite_policy_from_config, wiki_write_lock   # verified: project.py:1197, :910, :695, :73
from parrot.knowledge.wiki.schema.store import SchemaStore                                     # TASK-3682
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig, TableRecord, ColumnRecord, LookupResult, SyncReport  # TASK-3680
from parrot.knowledge.wiki.schema.ids import normalize_ref, parse_table_id, table_concept_id, source_concept_id, schema_concept_id  # TASK-3680
from parrot.knowledge.wiki.schema.render import render_page, render_source_page, render_schema_page, content_hash   # TASK-3681
from parrot.knowledge.wiki.schema.producers.live import introspect                             # TASK-3683
from parrot.bots.database.models import TableMetadata, Completeness                            # verified: bots/database/models.py:131, :97
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:116-143 (template)
@classmethod def from_root(cls, root: Path | None = None) -> "LedgerService":
    shared_root = find_shared_root(root) or (root or Path.cwd()).resolve()
    config = load_effective_config(shared_root).config          # never raw load_project_config (call-site guard test)
    ledger_dir = config.ledger_path(shared_root); ledger_dir.mkdir(parents=True, exist_ok=True)
    store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=sqlite_policy_from_config(config))
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py — BaseWikiStore
    async def get_page(self, concept_id, include_body=True) -> Optional[dict]        # :565
    async def search_fts(self, query, category=None, limit=10) -> list[dict]          # :576
    async def neighbors(self, concept_id, rel=None, direction="both") -> list[dict]   # :582  (rows carry concept_id/rel/direction)
    async def page_hashes(self, concept_ids) -> dict[str, Optional[str]]              # :837
# TASK-3682 SchemaStore: upsert_columns, columns_for, find_columns, replace_schema_slice(origin, pages, columns, edges)
# TASK-3680 WikiProjectConfig.schema: SchemaPlaneConfig ; schema_path(root) -> root/.parrot/schema
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:73 wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]
```

### Does NOT Exist
- ~~`LedgerService.from_dir()`~~ — FEAT-569 TASK-3354, NOT merged; write `from_dir` here independently
- ~~`StructuralService(read_repair=False)`~~ — FEAT-569 TASK-3353, not merged
- ~~`load_project_config` direct use~~ — forbidden by the call-site guard; use `load_effective_config(root).config`
- ~~`FederatedWikiStore` inside the service~~ — the service owns ONE SchemaStore; federation happens in mcp_server (TASK-3690)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_service.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#sqlite_policy_from_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.neighbors",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.page_hashes"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`ledger/service.py:116-143 LedgerService.from_root` for construction; `structural/service.py:431-479 _ensure_fresh` for `page_hashes` drift detection.

### Key Constraints
- `sync` replaces only the `schema:<origin>` slice; memory pages (`origin='memory'`) are untouched (AC7).
- `changed_only` compares `content_hash` via `page_hashes()` and rewrites only drifted tables (AC2).
- Read methods never introspect a database (G4).
- `from_dir(read_only=True)` default; writes need `read_only=False`.

### References in Codebase
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:116-143
- packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:431-479
- sdd/specs/sql-schema-plane.spec.md §3 Module 2

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Create `service.py` from the block — why: fixes the read/write API every later task depends on.
2. Implement `from_root` exactly like `LedgerService.from_root` and `from_dir` without any git lookup — why: rootless DatabaseAgent (AC12).
3. Implement `sync` = introspect → render → `replace_schema_slice`; with `changed_only`, filter by `page_hashes` first — why: AC2.
4. Implement `lookup`/`neighbors`/`search`/reader methods over the store only — why: G4.
5. Tests with a fake toolkit injected through `introspect(toolkit=…)`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` (CREATE)
```python
"""SchemaPlaneService — application-facing service over SchemaStore (FEAT-600 M2; mirrors LedgerService)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from parrot.bots.database.models import TableMetadata  # verified: bots/database/models.py:131
from parrot.knowledge.wiki.project import find_shared_root, load_effective_config, sqlite_policy_from_config  # verified: project.py:1197, :910, :695
from parrot.knowledge.wiki.schema.ids import normalize_ref, parse_table_id, table_concept_id
from parrot.knowledge.wiki.schema.models import LookupResult, SchemaPlaneConfig, SchemaSourceConfig, SyncReport, TableRecord
from parrot.knowledge.wiki.schema.producers.live import introspect
from parrot.knowledge.wiki.schema.render import content_hash, render_page, render_schema_page, render_source_page
from parrot.knowledge.wiki.schema.store import SchemaStore

logger = logging.getLogger(__name__)


class SchemaPlaneReader(Protocol):
    """Read/write surface consumed by CachePartition (TASK-3691) — keeps bots/database free of wiki imports."""

    async def get_table(self, origin: str, schema: str, table: str) -> Optional[TableMetadata]: ...
    async def put_table(self, origin: str, dialect: str, metadata: TableMetadata) -> None: ...
    async def list_tables(self, origin: str, schema: Optional[str] = None) -> list[str]: ...


class SchemaPlaneService:
    """Coordinates the schema plane: sync from live sources, lookups, join-path neighbors, FTS."""

    def __init__(self, store: SchemaStore, config: SchemaPlaneConfig, plane_dir: Path, shared_root: Optional[Path]) -> None:
        self._store, self.config, self.plane_dir, self.shared_root = store, config, plane_dir, shared_root
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_root(cls, root: Optional[Path] = None) -> "SchemaPlaneService":
        """find_shared_root → load_effective_config → config.schema_path → SchemaStore(dir/'schema.db') (ledger/service.py:116 shape)."""
        shared_root = find_shared_root(root) or (root or Path.cwd()).resolve()
        config = load_effective_config(shared_root).config
        plane_dir = config.schema_path(shared_root)
        plane_dir.mkdir(parents=True, exist_ok=True)
        store = SchemaStore(plane_dir / "schema.db", wiki_name="schema", sqlite_policy=sqlite_policy_from_config(config))
        return cls(store, config.schema, plane_dir, shared_root)

    @classmethod
    def from_dir(cls, plane_dir: Path, *, config: Optional[SchemaPlaneConfig] = None, read_only: bool = True) -> "SchemaPlaneService":
        """Rootless constructor for a DatabaseAgent without a git checkout (no find_shared_root, no wiki.json)."""
        plane_dir.mkdir(parents=True, exist_ok=True)
        store = SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=read_only)
        return cls(store, config or SchemaPlaneConfig(), plane_dir, None)

    @property
    def store(self) -> SchemaStore:
        return self._store

    async def sync(self, origin: str, *, tables: Optional[list[str]] = None, changed_only: bool = False,
                   dsn_resolver: Optional[Callable[[str], str]] = None, toolkit: Any = None) -> SyncReport:
        """Introspect ``origin`` and replace its ``schema:<origin>`` slice; ``changed_only`` rewrites drifted tables only."""
        cfg = self.config.sources[origin]
        dsn = (dsn_resolver or _env_dsn)(cfg.dsn_env)
        records, failed = await introspect(cfg, dsn, tables=tables, toolkit=toolkit)
        report = SyncReport(failed=failed)
        ids = [table_concept_id(r.origin, r.metadata.schema, r.metadata.tablename) for r in records]
        known = await self._store.page_hashes(ids)  # verified: store.py:837
        for r, tid in zip(records, ids, strict=True):
            (report.unchanged if known.get(tid) == r.content_hash else (report.updated if known.get(tid) else report.created)).append(tid)
        # FILL IN: when changed_only, keep only created+updated records for the write; when a table_id was in the old slice but is now absent
        #   (and `tables` was None) append it to report.removed — bounded by AC2 (unchanged ⇒ nothing rewritten) and "removed pages logged"
        pages, columns, edges = [render_source_page(cfg)], [], []
        for r in records:
            page, cols, eds = render_page(r)
            pages.append(page); columns.extend(cols); edges.extend(eds)
        # FILL IN: one render_schema_page per distinct schema + (source→schema "contains") edges — bounded by spec §2 Edges
        await self._store.replace_schema_slice(origin, pages, columns, edges)
        return report

    async def lookup(self, ref: str) -> LookupResult | list[str]:
        """normalize_ref → page + columns + neighbors; age from introspected_at; stale per stale_after_days[completeness]."""
        tid = normalize_ref(ref, sources=self.config.sources)
        if not isinstance(tid, str):
            return tid
        page = await self._store.get_page(tid)  # verified: store.py:565
        # FILL IN: build LookupResult (frontmatter from page body, ddl section, columns_for, neighbors(rel=None) split into relations vs `about`
        #   annotations, age_days, stale) — bounded by AC3 and G4 (no introspection); raise KeyError when page is None
        raise NotImplementedError

    async def neighbors(self, ref: str, *, depth: int = 1, rel: Optional[str] = "references") -> list[dict[str, Any]]:
        """FK graph walk to ``depth``; each hop carries the column pair from columns.fk_target."""
        # FILL IN: BFS over self._store.neighbors(tid, rel=rel) (store.py:582) joining columns_for(src) fk_target → dst — bounded by depth
        raise NotImplementedError

    async def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """search_fts(category='table') merged with find_columns(name=query) hits, deduplicated by table id."""
        # FILL IN — bounded by limit
        raise NotImplementedError

    async def sources(self) -> list[SchemaSourceConfig]:
        return list(self.config.sources.values())

    # ---- SchemaPlaneReader ---------------------------------------------------------------
    async def get_table(self, origin: str, schema: str, table: str) -> Optional[TableMetadata]:
        """Rebuild a TableMetadata from the stored page + columns; None when absent. Never introspects."""
        # FILL IN: page frontmatter + columns_for → TableMetadata(source=frontmatter['source'], completeness=…) — bounded by G4
        raise NotImplementedError

    async def put_table(self, origin: str, dialect: str, metadata: TableMetadata) -> None:
        """Write-through of one table (CachePartition tier); upserts page + columns + edges without touching other tables."""
        rec = TableRecord(origin=origin, dialect=dialect, metadata=metadata, content_hash=content_hash(metadata),
                          introspected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        page, cols, eds = render_page(rec)
        await self._store.upsert_pages([page]); await self._store.upsert_columns(cols); await self._store.add_edges(list(eds))

    async def list_tables(self, origin: str, schema: Optional[str] = None) -> list[str]:
        # FILL IN: list_pages(category="table") filtered by parse_table_id origin/schema — bounded by read-only
        raise NotImplementedError


def _env_dsn(name: str) -> str:
    """Default DSN resolver: environment variable NAME → value (navconfig lookup is the CLI's job, TASK-3687)."""
    import os
    return os.environ[name]
```
**Why**: `from_root` is byte-for-byte the ledger shape (shared-root policy); `from_dir` implements the brainstorm's production decision without waiting for FEAT-569. `put_table` exists so the CachePartition tier (TASK-3691) can write through via the Protocol only.

### FILL IN checklist
- [ ] `sync` changed_only filtering + removed detection — AC2
- [ ] `sync` schema pages + source→schema edges — spec §2 Edges
- [ ] `lookup` result assembly — AC3/G4
- [ ] `neighbors` BFS with column pairs — depth bound
- [ ] `search` merge — limit
- [ ] `get_table` rebuild — G4
- [ ] `list_tables`
- [ ] tests: from_dir read-only refuses writes; sync report buckets; changed_only rewrites one; memory annotation survives; lookup age/stale; neighbors join path

---

## Acceptance Criteria

- [ ] `from_root` and `from_dir` both open `schema.db`; `from_dir(read_only=True)` write raises `PermissionError` (AC12)
- [ ] `sync` with a fake toolkit produces `created`; second sync `unchanged`; changed column → exactly one `updated` and one page rewritten (AC2)
- [ ] a `mem-*` page linked `about` a table survives `sync` (AC7)
- [ ] `lookup('bigquery:epson.sales') == lookup('table:bigquery/epson.sales')` (AC3)
- [ ] `neighbors(depth=2)` returns hops with `(src_col, dst_col)`
- [ ] no database call happens in `lookup`/`neighbors`/`search`/`get_table` (assert fake toolkit untouched)
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_service.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_service.py
import pytest
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig, SchemaSourceConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService

class FakeTK:
    def __init__(self, meta): self.meta = meta; self.calls = 0
    async def describe_table(self, schema, table): self.calls += 1; return self.meta

@pytest.fixture
def schema_service(plane_dir):
    cfg = SchemaPlaneConfig(sources={"bigquery": SchemaSourceConfig(alias="bigquery", dialect="bigquery", dsn_env="X", allowed_schemas=["epson"], tables=["epson.sales"])})
    return SchemaPlaneService.from_dir(plane_dir, config=cfg, read_only=False)

async def test_sync_then_unchanged(schema_service, sales_metadata):
    tk = FakeTK(sales_metadata)
    r1 = await schema_service.sync("bigquery", dsn_resolver=lambda n: "dsn", toolkit=tk)
    r2 = await schema_service.sync("bigquery", dsn_resolver=lambda n: "dsn", toolkit=tk, changed_only=True)
    assert r1.created == ["table:bigquery/epson.sales"] and r2.unchanged == ["table:bigquery/epson.sales"]

async def test_lookup_forms_equal(schema_service, sales_metadata):
    await schema_service.sync("bigquery", dsn_resolver=lambda n: "dsn", toolkit=FakeTK(sales_metadata))
    a = await schema_service.lookup("bigquery:epson.sales"); b = await schema_service.lookup("table:bigquery/epson.sales")
    assert a == b and a.page_id == "table:bigquery/epson.sales"
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3680, TASK-3681, TASK-3682, TASK-3683` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: gpt-5.6-terra, backend: codex, attempt_uid b52d6a9c689540178191da17d8596c27)
**Date**: 2026-09-24
**Notes**: Implementation commit `7b18eccf4` + engine lint-autofix commit `db6bcbdce` (merge `88f322dc8`). `SchemaPlaneService`: `from_root`/`from_dir`, sync, lookup, neighbors, search, `SchemaPlaneReader`. Engine-side merge fidelity check passed (`unexpected_files: []`).
**Merge validation**: merge-tier (root scope) 4 failed, 1132 passed, 7 skipped, 20 warnings in 68.33s — same 4 pre-existing/environmental failures as prior chunks (see `issue:33fe54e65d2d`), unrelated to this task's files. Reviewed via `coder-review:76296e3d197cdb1b23ad2511`, zero fix commits needed.

**Post-merge adversarial review fix**: an independent code-review pass found `test_sync_then_unchanged_and_lookup` (`test_service.py`) comparing two `LookupResult` objects for full equality across two separate `lookup()` calls; `LookupResult.age_days` is computed live from `datetime.now(timezone.utc)` on every call (`service.py:269`), so two calls microseconds apart almost never produce bit-identical floats — a test-authoring bug (broken, not flaky), not an implementation defect; the underlying lookup/normalization behavior itself is correct. Fixed by comparing `model_dump(exclude={"age_days"})` for exact equality and asserting `age_days` values are merely close (`pytest.approx(..., abs=1.0)` days). Verified: full `tests/knowledge/wiki/schema/` suite green (46 passed); `ruff check`/`black --check` clean.
**Model feedback NOT recorded**: `coder_record_feedback` requires the execution's `execution_id`, not preserved through a context-compaction boundary before this review fix landed. This is a test-authoring correction, not an implementation defect, so no model-behavior pattern applies to `service.py` itself.

**Deviations from spec**: none
