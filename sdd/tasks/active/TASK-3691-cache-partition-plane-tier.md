# TASK-3691: `CachePartition` plane tier + write-through; `DatabaseToolkitConfig.origin` / `DatabaseToolkit(origin=)`

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3684
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (cache half). Inserts the plane between Redis and the vector store in `CachePartition.get` (cache.py:112-183) and writes through in `store_table_metadata` (:185) when `plane_write=True`. Behaviour must be byte-identical when `plane is None` (AC8). `bots/database` gains NO import-time dependency on `parrot.knowledge.wiki` (AC13). `origin` (brainstorm decision) is declared on `DatabaseToolkitConfig` and the `DatabaseToolkit` constructor, defaulting to `database_type`.

---

## Scope

- Modify `cache.py`: `CachePartition.__init__(…, plane=None, plane_write=False, origin=None, dialect=None)`; Tier 2b in `get()`; write-through in `store_table_metadata`.
- Modify `toolkits/base.py`: `DatabaseToolkitConfig.origin: Optional[str]`; `DatabaseToolkit.__init__(…, origin: Optional[str] = None)` → `self.origin = origin or database_type`.
- Write `test_cache_plane_tier.py` (fake reader) including the import-isolation test (AC13).

**NOT in scope**: SQLToolkit repair/warm (TASK-3692), DatabaseAgent wiring (TASK-3693), any change to `CacheManager.create_partition` signature beyond passing kwargs through.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/cache.py` | MODIFY | plane tier + write-through |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py` | MODIFY | origin field + kwarg |
| `packages/ai-parrot/tests/bots/database/test_cache_plane_tier.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from typing import TYPE_CHECKING, Optional
if TYPE_CHECKING:  # never at runtime — AC13
    from parrot.knowledge.wiki.schema.service import SchemaPlaneReader   # TASK-3684 (Protocol: get_table/put_table/list_tables)
from parrot.bots.database.models import TableMetadata, Completeness       # verified: packages/ai-parrot/src/parrot/bots/database/models.py:131, :97
from parrot.bots.database.cache import CachePartition, CachePartitionConfig, CacheManager   # verified: cache.py:54, :33, :612
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/cache.py
class CachePartition:                                                                       # :54
    def __init__(self, ..., lru_ttl: int = 1800, redis_ttl: int = 3600, vector_store: Optional["AbstractStore"] = None,   # :70-73
                 ttl_by_completeness: Optional[Dict[int, int]] = None,                       # :74  ← add plane kwargs after this line
        ...  self.vector_store = vector_store; self.vector_enabled = vector_store is not None   # :91-92 ← add plane attrs after :92
    async def get(self, schema_name, table_name, *, required=Completeness.NAME_ONLY, max_age=None) -> Optional[TableMetadata]   # :112
        # Tier 2: Redis (:143-147) … `# Tier 3: Vector store (point lookup)` (:149) ← insert Tier 2b ABOVE this comment
    async def store_table_metadata(self, metadata: TableMetadata) -> None                    # :185 (writes LRU, schema_cache, Redis, vector) ← append plane write-through at the END of the method
class CacheManager: def create_partition(self, config: CachePartitionConfig) -> CachePartition   # :612/:656
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class DatabaseToolkitConfig(BaseModel): ... database_type: str = Field(default="postgresql")   # :31, :55 ← add `origin` after
class DatabaseToolkit(AbstractToolkit, ABC):                                                 # :78
    def __init__(self, dsn, allowed_schemas=None, primary_schema=None, tables=None, read_only=True, cache_partition=None,
                 retry_config=None, database_type="postgresql", use_pool=False, pool_params=None, **kwargs)   # :104-118 ← add `origin: Optional[str] = None`
        self.database_type = database_type                                                   # :136 ← add `self.origin = origin or database_type` after
```

### Does NOT Exist
- ~~a durable tier in `CachePartition`~~ — tiers are LRU / schema_cache / Redis / vector (cache.py:122); this task adds the plane tier
- ~~`CachePartition.plane`, `plane_write`, `origin`, `dialect`~~ — new attributes added here
- ~~`DatabaseToolkitConfig.origin` / `DatabaseToolkit.origin`~~ — new
- ~~runtime import of `parrot.knowledge.wiki` in `bots/database`~~ — forbidden (AC13); Protocol under TYPE_CHECKING only
- ~~`parrot_tools.database.models.TableMetadata`~~ — legacy duplicate; never import it here (F022)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/database/cache.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/database/toolkits/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/database/test_cache_plane_tier.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/database/cache.py#CachePartition",
    "sym:packages/ai-parrot/src/parrot/bots/database/cache.py#CachePartition.get",
    "sym:packages/ai-parrot/src/parrot/bots/database/cache.py#CachePartition.store_table_metadata",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/base.py#DatabaseToolkitConfig",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/base.py#DatabaseToolkit"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
cache.py:143-153 — the Redis and vector tiers (`if metadata is None and …: metadata = await …; if metadata is not None: self.hot_cache[cache_key] = metadata`).

### Key Constraints
- With `plane is None` every code path is unchanged — `pytest packages/ai-parrot/tests/bots/database/test_cache.py` must pass without edits (AC8).
- Plane tier is consulted AFTER Redis and BEFORE the vector store.
- Write-through only when `plane_write` is True; errors from the plane are logged, never raised (best-effort tier).
- No `parrot.knowledge.wiki` import at module import time (AC13 test blocks it in `sys.modules`).

### References in Codebase
- packages/ai-parrot/src/parrot/bots/database/cache.py:112-200
- packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:31-60, :104-140
- packages/ai-parrot/tests/bots/database/test_cache.py — parity suite

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Add the four kwargs and attributes to `CachePartition.__init__` — why: opt-in, default off (AC8).
2. Insert Tier 2b in `get()` above the vector-store comment — why: plane is durable and cheaper than the vector store, but Redis stays first (hot).
3. Append write-through to `store_table_metadata` — why: successful introspections populate the plane (G5).
4. Add `origin` to `DatabaseToolkitConfig` and the toolkit constructor — why: alias key for the plane (brainstorm decision); `tk_id` untouched.
5. Tests with a fake reader + `sys.modules` blocking test.

### `packages/ai-parrot/src/parrot/bots/database/cache.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        ttl_by_completeness: Optional[Dict[int, int]] = None,' packages/ai-parrot/src/parrot/bots/database/cache.py) → cache.py:74
# AFTER — insert below (still inside CachePartition.__init__'s parameter list):
        plane: Optional["SchemaPlaneReader"] = None,
        plane_write: bool = False,
        origin: Optional[str] = None,
        dialect: Optional[str] = None,

# occurrences: 1 (verified: grep -c '        self.vector_enabled = vector_store is not None' …/cache.py) → cache.py:92
# AFTER — insert below:
        # FEAT-600: optional durable schema-plane tier (after Redis, before the vector store). None ⇒ behaviour unchanged.
        self.plane = plane
        self.plane_write = plane_write and plane is not None
        self.origin = origin
        self.dialect = dialect

# occurrences: 1 (verified: grep -c '        # Tier 3: Vector store (point lookup)' …/cache.py) → cache.py:149
# BEFORE — insert ABOVE this comment:
        # Tier 2b: schema plane (FEAT-600) — durable, never introspects
        if metadata is None and self.plane is not None and self.origin:
            try:
                metadata = await self.plane.get_table(self.origin, schema_name, table_name)
            except Exception as exc:  # noqa: BLE001 — the plane is a best-effort tier
                self.logger.warning("schema plane lookup failed for %s.%s: %s", schema_name, table_name, exc)
                metadata = None
            if metadata is not None:
                self.hot_cache[cache_key] = metadata

# occurrences: 1 (verified: grep -c '    async def store_table_metadata(self, metadata: TableMetadata) -> None:' …/cache.py) → cache.py:185
# AT THE END of store_table_metadata's body (after the last existing tier write):
        if self.plane_write and self.origin:
            try:
                await self.plane.put_table(self.origin, self.dialect or self.origin, metadata)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("schema plane write-through failed for %s: %s", metadata.full_name, exc)
# top of file, with the other typing imports:
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # FEAT-600 — typing only; bots/database must not import the wiki at runtime (AC13)
    from parrot.knowledge.wiki.schema.service import SchemaPlaneReader
```
**Why**: Tier position and opt-in defaults come from spec M6; the `TYPE_CHECKING` import is what keeps AC13 true. `self.logger` already exists on CachePartition — FILL IN: verify with `grep -n 'self.logger' cache.py`, else use `logging.getLogger(__name__)`.

### `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    database_type: str = Field(default="postgresql")' packages/ai-parrot/src/parrot/bots/database/toolkits/base.py) → base.py:55
# AFTER — insert below:
    origin: Optional[str] = Field(default=None, description="Schema-plane origin alias (FEAT-600); defaults to database_type")

# occurrences: 1 (verified: grep -c '        retry_config: Optional[QueryRetryConfig] = None,' …/base.py) → base.py:112
# AFTER — insert below (constructor parameter):
        origin: Optional[str] = None,

# occurrences: 1 (verified: grep -c '        self.database_type = database_type' …/base.py) → base.py:136
# AFTER — insert below:
        self.origin = origin or database_type  # FEAT-600: plane alias; tk_id (agent.py:206) is NOT derived from this
```
**Why**: Brainstorm decision: origin is an explicit alias defaulting to the dialect; `tk_id` keeps the router working.

### FILL IN checklist
- [ ] `self.logger` availability on CachePartition — verify or fall back to module logger
- [ ] tests: tier order (LRU/Redis miss → plane hit → hot_cache set, vector store not called); `plane_write=False` never calls `put_table`; `True` does; parity: `test_cache.py` untouched and green; `DatabaseToolkit(origin=None).origin == database_type`; AC13 import block

---

## Acceptance Criteria

- [ ] miss in LRU/Redis served from the plane before the vector store; hot_cache populated (AC8)
- [ ] `plane_write` gate honoured
- [ ] `pytest packages/ai-parrot/tests/bots/database/test_cache.py -q` passes unmodified (AC8)
- [ ] importing `parrot.bots.database.cache` with `parrot.knowledge.wiki` set to `None` in `sys.modules` succeeds (AC13)
- [ ] `DatabaseToolkitConfig(origin=None)` validates; `DatabaseToolkit(...).origin == database_type` by default
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/database/test_cache_plane_tier.py -q`
- `pytest packages/ai-parrot/tests/bots/database/test_cache.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_cache_plane_tier.py
import sys, importlib
import pytest
from parrot.bots.database.cache import CachePartition

class FakePlane:
    def __init__(self, meta): self.meta, self.puts = meta, []
    async def get_table(self, origin, schema, table): return self.meta
    async def put_table(self, origin, dialect, meta): self.puts.append((origin, dialect, meta.tablename))
    async def list_tables(self, origin, schema=None): return []

@pytest.fixture
def sales_metadata():
    from parrot.bots.database.models import TableMetadata, Completeness
    return TableMetadata(schema="epson", tablename="sales", table_type="BASE TABLE", full_name="epson.sales", completeness=Completeness.FULL)

async def test_plane_tier_hit(sales_metadata):
    plane = FakePlane(sales_metadata)
    part = CachePartition(namespace="t", plane=plane, origin="bigquery")   # FILL IN: exact positional/keyword args per cache.py:60-75
    assert (await part.get("epson", "sales")) is sales_metadata

async def test_write_through_gate(sales_metadata):
    plane = FakePlane(None)
    part = CachePartition(namespace="t", plane=plane, origin="bigquery", plane_write=True)
    await part.store_table_metadata(sales_metadata)
    assert plane.puts == [("bigquery", "bigquery", "sales")]

def test_no_wiki_import_at_runtime(monkeypatch):
    monkeypatch.setitem(sys.modules, "parrot.knowledge.wiki", None)
    for m in [k for k in sys.modules if k.startswith("parrot.bots.database.cache")]:
        monkeypatch.delitem(sys.modules, m)
    importlib.import_module("parrot.bots.database.cache")
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3684` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
