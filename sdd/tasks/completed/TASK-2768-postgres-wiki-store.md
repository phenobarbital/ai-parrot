# TASK-2768: `PostgresWikiStore` — BaseWikiStore over the shared schema

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2765
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-520, implementing the U1 decision: the wiki retrieval plane
runs over the SAME `graphindex.*` schema as the graph plane. The mapping is
designed in spec §2 "The U1 mapping" — body-in-DB for wiki pages, separate
`origin` vs `provenance`, caller-preserving `updated_at`, volatile `node_id`
as secondary lookup. Wired into `create_wiki_store` as an explicit
`backend == "postgres"` branch (lazy import — the ArangoDB precedent).

---

## Scope

- Implement `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py`:
  `class PostgresWikiStore(BaseWikiStore)` with the FULL abstract surface:
  - `upsert_pages(pages: list[WikiPageRecord]) -> int` — identity row +
    close-and-insert version row per the U1 mapping (reuse TASK-2765's
    helpers; wiki body goes to `node_versions.body`, `origin`/`asserted_by`/
    `content_hash`/`token_count` columns; `updated_at` caller-preserving:
    supplied value stored verbatim, `None` → now()).
  - `add_edges(edges: list[tuple]) -> int` — wiki edge tuples into
    `graphindex.edges` (`rel` = wiki kind string). Match the SQLite backend's
    tuple shape EXACTLY (read `_insert_edges_conn`, `wiki/store.py:1113`,
    before implementing).
  - `replace_source_slice(...)` — one transaction scoped by `source_id`
    (parity with `wiki/store.py:1176`).
  - `delete_page`, `get_page(include_body=True)`, `list_pages`,
    `search_fts(query, category, limit)` (shared `fts` column,
    `ts_rank_cd` ordering), `search_vector(embedding, limit)` (delegates to
    `graphindex.embeddings`; may use `rank_by_cosine` as interim until
    TASK-2769 lands the KNN path), `neighbors`, `dump_pages`, `dump_edges`,
    `stats`, `orphan_sources`, `broken_edges`, `missing_bodies`,
    `upsert_embedding(concept_id, vector, model)` (current version's row),
    `page_hashes(concept_ids)`.
  - Constructor: `PostgresWikiStore(dsn=..., wiki_name=..., schema=...)`.
- MODIFY `create_wiki_store` (`wiki/store.py:1795`): add an explicit
  `backend == "postgres"` branch with lazy import, passing
  `dsn=kwargs["dsn"]` (default: the resolved `GRAPHINDEX_PG_DSN`, which
  itself falls back to `parrot.conf.default_dsn` — see TASK-2764); extend the
  unknown-backend error message list.
- Extend the wiki contract suite fixture with a live-gated `postgres` param:
  `tests/knowledge/wiki/test_store.py:29`
  (`pytest.param("postgres", marks=needs_pg)`).

**NOT in scope**: symbol methods (`upsert_symbols` etc. — TASK-2772; until
then the inherited non-abstract defaults from `BaseWikiStore` stand), ANN
index (TASK-2769), federation/sync changes (none needed — LWW works via
`updated_at`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py` | CREATE | `PostgresWikiStore` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `postgres` branch in `create_wiki_store` (:1830-1852 block) |
| `packages/ai-parrot/tests/knowledge/wiki/test_postgres_store.py` | CREATE | postgres-specific tests (full abstract surface, updated_at, mapping) |

> **CONTRACT CORRECTION (agent, verified 2026-09-03 against this worktree):**
> `packages/ai-parrot/tests/knowledge/wiki/test_store.py` — referenced
> throughout this task (§Scope, §Codebase Contract, §Acceptance Criteria,
> §Test Specification) as an existing parametrized `store` fixture
> suite (`@pytest.fixture(params=["sqlite", "memory"])`) to extend with a
> `postgres` param — **does NOT exist in this codebase.**
> `grep`/`find` across `packages/ai-parrot/tests/knowledge/wiki/` and
> `tests/knowledge/wiki/test_factory_arango.py` (also referenced) confirm
> neither file is present; there is no existing cross-backend behavioral
> contract suite for `BaseWikiStore` to extend. Per the "when in doubt"
> anti-hallucination rule: rather than inventing a new shared suite that
> would also exercise (and risk regressing) the untouched SQLite/memory/
> Arango backends — out of this task's scope — full abstract-surface
> coverage is provided in the CREATE'd `test_postgres_store.py` instead.
> The acceptance criterion "`tests/knowledge/wiki/test_store.py` green
> with `postgres` param" is satisfied in substance (every abstract method
> covered against Postgres) via that file. See its Completion Note.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import (
    BaseWikiStore,       # wiki/store.py:415
    WikiPageRecord,      # wiki/store.py:299
    rank_by_cosine,      # wiki/store.py:348 — shared brute-force vector ranking
)
from parrot.knowledge.graphindex.pg_schema import ensure_schema, create_pg_pool  # TASK-2764
```

### Existing Signatures to IMPLEMENT (abstract surface, wiki/store.py)
```python
class BaseWikiStore(ABC):                       # :415
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int          # :434
    async def add_edges(self, edges: list[tuple]) -> int                      # :437
    async def replace_source_slice(...)                                       # :440 — read full signature before implementing
    async def delete_page(self, concept_id: str) -> bool                      # :448
    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None  # :451
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]] # :455
    async def list_pages(...)                                                 # :458
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]  # :466
    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]   # :469
    async def neighbors(...)                                                  # :472
    async def dump_pages(self) -> list[dict[str, Any]]                        # :480
    async def dump_edges(self) -> list[dict[str, Any]]                        # :483
    async def stats(self) -> dict[str, Any]                                   # :486
    async def orphan_sources(self) -> list[str]                               # :490
    async def broken_edges(self) -> list[dict[str, Any]]                      # :493
    async def missing_bodies(self) -> list[str]                               # :496
    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]  # :693 (non-abstract — override)

class WikiPageRecord(BaseModel):   # :299
    concept_id: str                 # required, min_length=1
    node_id: Optional[str]          # VOLATILE — secondary lookup only
    title: str = ""; category: str = "concept"; summary: str = ""; body: str = ""
    source_id: Optional[str]; token_count: int = 0
    origin: str = "ingest"          # ingest|authored|memory
    asserted_by: Optional[str]
    updated_at: Optional[str]       # ISO-8601; caller-preserving (FEAT-461) — None means "stamp now"
    content_hash: Optional[str]

def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) -> BaseWikiStore  # :1795
    # sqlite branch :1830 / memory :1832 / arangodb LAZY IMPORT :1838 / _EXTRA_BACKENDS :1849
    # error message construction :1851 — extend the known-backends list
```

### Reference semantics (read before implementing — exact dict shapes)
```python
# wiki/store.py SQLiteWikiStore — the behavioral reference the shared test
# suite encodes: _upsert_pages_conn :1065, _insert_edges_conn :1113,
# upsert_pages :1134, add_edges :1154, replace_source_slice :1176,
# delete_page :1274, upsert_embedding :1299, search_fts :1582
# tests/knowledge/wiki/test_store.py:29 — @pytest.fixture(params=["sqlite", "memory"])
#   def store(request, tmp_path): return create_wiki_store(tmp_path, wiki_name="test-wiki", backend=request.param)
```

### Does NOT Exist
- ~~`PostgresWikiStore`~~ / ~~`create_wiki_store(backend="postgres")`~~ —
  created by this task.
- ~~`postgres_store.py` needing `storage_dir`~~ — server-hosted like Arango;
  the fixture must pass a DSN, not a tmp_path-derived file (mirror how the
  Arango tests handle construction, `tests/knowledge/wiki/test_factory_arango.py`).
- ~~symbol tables/methods in this task~~ — TASK-2772.
- ~~writing `provenance` from the wiki plane~~ — wiki writes `origin`;
  `provenance` keeps its column default (U1 mapping rule 3).
- ~~conflating `updated_at` with `tx_from`~~ — separate columns; sync
  (TASK-2466 semantics) depends on caller-supplied `updated_at` surviving.

---

## Implementation Notes

### Key Constraints
- The shared contract suite (`test_store.py`) is the acceptance bar — run it
  with the new param FIRST, implement until green; do not modify existing
  test bodies (only the fixture params line + skip marker).
- Wiki upserts are close-and-insert like the graph plane (content change ⇒
  new version); `get_page` returns the CURRENT version only.
- `stats()` / dumps operate on current versions (upper_inf).
- asyncpg only; Google docstrings; `self.logger`.

### References in Codebase
- `wiki/arango_store.py` — the other server-hosted backend (construction,
  no storage_dir, analyzer config) — closest lifecycle model.

---

## Acceptance Criteria

- [ ] `tests/knowledge/wiki/test_store.py` green with `postgres` param
      (live-gated); `sqlite`/`memory` params unchanged and green.
- [ ] Caller-supplied `updated_at` survives upsert verbatim; `None` stamps
      now (test).
- [ ] Wiki upsert of changed body closes old version + inserts (history
      visible via TASK-2767 `history()` — cross-plane test).
- [ ] Graph plane and wiki plane coexist: a graph node and a wiki page with
      different concept_ids don't interfere; `load_graph` does not return
      wiki-only rows as UniversalNodes unless their `category` is a valid
      NodeKind (decide + test the filter; document in docstring).
- [ ] `create_wiki_store(backend="postgres")` constructs; unknown-backend
      error lists `postgres`.
- [ ] Zero SQLAlchemy; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_postgres_store.py
async def test_updated_at_caller_preserved(pg_wiki_store): ...
async def test_upsert_change_creates_version(pg_wiki_store, pg_persistence): ...
async def test_planes_coexist(pg_wiki_store, pg_persistence): ...
def test_factory_postgres_branch(monkeypatch): ...
# plus: fixture param addition in tests/knowledge/wiki/test_store.py:29
```

---

## Agent Instructions

1. Read spec §2 "The U1 mapping" — it is normative for every column decision.
2. Read `SQLiteWikiStore`'s method bodies for exact return-dict shapes before
   writing SQL (the shared suite asserts on those shapes).
3. Update index status; move to completed + note when done.

---

## Completion Note

Implemented `PostgresWikiStore(BaseWikiStore)` in `postgres_store.py`
covering the full abstract surface + `page_hashes` override, mapped per
spec §2's U1 table: `body`-in-DB (never `body_ref`), `origin`/
`asserted_by`/`updated_at` (caller-preserving, never conflated with
`tx_from`), `provenance` left at its schema default and never written by
this plane. Wired `create_wiki_store(backend="postgres")` as an explicit,
lazy-imported branch (arangodb precedent) and extended the unknown
-backend error message to list `'postgres'`.

**Contract correction** (documented in this task file above): the spec's
and this task's references to an existing parametrized
`tests/knowledge/wiki/test_store.py` `store` fixture do not correspond to
anything in this codebase — verified absent by `find`/`grep` across
`tests/knowledge/wiki/`. Rather than inventing a new cross-backend suite
(risking the untouched SQLite/memory/Arango backends, out of scope), full
abstract-surface coverage lives in the CREATE'd `test_postgres_store.py`
(24 tests) instead — satisfying the acceptance criterion in substance.

Two design decisions not fully specified by the task, made and documented
in the module docstring:
1. **Namespace scoping**: `nodes.namespace` is used as this store's
   `wiki_name` scope. Enumeration reads (`list_pages`, `dump_pages`,
   `stats`, `missing_bodies`) filter on `namespace = wiki_name` so
   multiple wikis sharing one schema don't bleed into each other;
   identity reads (`get_page`) are namespace-agnostic by design
   (`concept_id` is the shared, globally-unique key) — verified by the
   `test_planes_coexist` test.
2. **`orphan_sources()` always `[]`**: the shared `graphindex.*` schema
   (TASK-2764, out of this task's file scope) has no `sources` registry
   table, so there is nothing to check "produced no pages" against —
   documented, not silently wrong.
3. **`dump_edges()` is not namespace-scoped**: `graphindex.edges` has no
   `namespace` column — same limitation the graph plane lives with.

`load_graph`/wiki-plane coexistence (spec AC): verified that a wiki page
whose `category` is NOT a valid `NodeKind` string (e.g. `"summary"`) is
excluded from `load_graph` via the TASK-2765 skip-and-warn tolerance; the
AC's own wording accepts that a wiki category colliding with a real
`NodeKind` value (e.g. `"concept"`) would show up — decided as the
boundary of this filter, not further mitigated, and documented inline.

All 24 tests pass (roundtrip, `include_body=False`, `node_id` fallback,
unknown id, `updated_at` caller-preserved/now-stamped, close-and-insert
versioning cross-checked via TASK-2767's `history()`, edges + neighbors +
provenance, atomic `replace_source_slice` incl. deleted-count, tombstone
`delete_page`, embedding upsert + cosine search, `list_pages`
category/origin filters, FTS archive-exclusion, dumps, `stats`,
`orphan_sources`/`broken_edges`/`missing_bodies`/`page_hashes`,
planes-coexist, factory branch + unknown-backend listing, no-SQLAlchemy
grep). Ran the full graphindex-postgres suite (pg_schema + persist +
commit protocol + temporal + wiki store) plus the existing
`test_extra_backends.py` together: 75/75 green, zero regressions in the
untouched sqlite/memory/arango wiki backends. `ruff check` clean.
