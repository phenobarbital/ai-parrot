# TASK-4376: HelixWikiStore core — pages, edges, search, lint

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4374, TASK-4375
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G1): `HelixWikiStore(BaseWikiStore)` is the HelixDB retrieval plane for one wiki,
at functional parity with `SQLiteWikiStore`. This task delivers the module, the plane schema, the
store class with the **whole abstract `BaseWikiStore` surface** (write, read, search, lint,
`rebuild_index`/`index_drift`), lazy bootstrap, the embedded-mode writer guard (AC13) and the
lazy factory the FEAT-540 `WikiBackendSpec` row (TASK-4392) will point at. The concrete-with-default
surface (CAS, meta, attrs public API, symbols, `page_hashes`) is TASK-4377 and the source manifest is
TASK-4378 — both extend this file / reuse its plane.

It speaks only to `parrot.knowledge.helix` (TASK-4372 settings/errors, TASK-4373 client, TASK-4374
bootstrap + DSL helpers). No `helixdb` import happens in this module at import time.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` with:
  - `WIKI_PLANE` (`PlaneSchema`, `schema_version=SCHEMA_VERSION`) declaring the labels `Page`, `Symbol`,
    `Source`, `Meta`, `PageAttr` (and `SOURCE_LABEL`, `PAGE_LABEL`, … `LabelSpec` constants re-used by
    TASK-4377/4378/4381/4382).
  - `HelixWikiStore(BaseWikiStore)`: `__init__`, `plane_schema` class attribute (subclasses override),
    `initialize()` (lazy, idempotent, `asyncio.Lock`), `close()`, `read_only` property,
    `_assert_writable()`, embedded `wiki.lock` guard.
  - Every abstract method: `upsert_pages`, `add_edges`, `replace_source_slice`, `delete_page`,
    `upsert_embedding`, `get_page`, `list_pages`, `search_fts`, `search_vector`, `neighbors`,
    `dump_pages`, `dump_edges`, `stats`, `orphan_sources`, `broken_edges`, `missing_bodies`, plus
    the overrides `rebuild_index` and `index_drift`.
  - Page attrs written **inside** the page batches (`upsert_pages`, `replace_source_slice`,
    `delete_page`) and returned by `get_page` (SQLite parity: `WikiPageRecord.attrs` is replaced in the
    same transaction, `get_page` carries `"attrs"`), and `Symbol` nodes of a source dropped by
    `replace_source_slice` (SQLite parity, `store.py:1972`).
  - `helix_wiki_store_factory(*, storage_dir=None, wiki_name="", **kwargs)`.
- Write `packages/ai-parrot/tests/knowledge/wiki/test_helix_store.py` (embedded `InMemory`).

**NOT in scope**: `compare_and_swap_page`, `get_meta`/`set_meta`, public `get_attrs`/`list_by_attrs`/
`upsert_attrs`, the symbol surface, `page_hashes` (TASK-4377); `HelixSourceBackend` (TASK-4378);
registering `"helixdb"` in any registry (TASK-4392); bulk `dump_attrs/meta/symbols/embeddings`
(TASK-4393); any edit to `wiki/store.py`, `project.py`, `sources.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` | CREATE | `WIKI_PLANE`, label constants, `HelixWikiStore` core, `helix_wiki_store_factory` |
| `packages/ai-parrot/tests/knowledge/wiki/test_helix_store.py` | CREATE | Parity tests on embedded InMemory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, SCHEMA_VERSION, estimate_tokens  # verified: wiki/store.py:697, :433, :51, :338
from parrot.knowledge.wiki.project import wiki_write_lock, LOCK_FILENAME  # verified: wiki/project.py:76, :51 (LOCK_FILENAME = "wiki.lock")
# Created by upstream FEAT-670 tasks (NOT on dev yet — verify in the worktree before use):
from parrot.knowledge.helix.settings import HelixSettings, HelixMode, resolve_helix_settings  # TASK-4372 (HelixSettings.with_database too)
from parrot.knowledge.helix.errors import HelixUnavailable, HelixWriteRejected  # TASK-4372
from parrot.knowledge.helix.client import HelixClient, open_helix_client, _sdk  # TASK-4373 (_sdk() = lazy helixdb module; write_batch()/read_batch() live there)
from parrot.knowledge.helix.bootstrap import PlaneSchema, LabelSpec, ensure_plane, ensure_vector_index, known_vector_dimensions  # TASK-4374
from parrot.knowledge.helix import dsl as hdsl  # TASK-4374: clamp_limit, MAX_SEARCH_LIMIT, lookup_by_key, upsert_node_entries, find_or_add_edge_entries, text_search, vector_search, cas_page_entries
```
`helixdb` is NOT installed in the shared `.venv` today (`python -c "import helixdb"` → ModuleNotFoundError);
TASK-4373 adds it to the root `dev` group. DSL op names come from the spec §6 "HelixDB SDK surface"
(wheel-verified list): `read_batch`, `write_batch`, `g`, `Predicate`, `BatchCondition`, `n_where`,
`n_with_label`, `out_e`, `in_e`, `add_n`, `add_e`, `set_property`, `drop`, `drop_edge`, `where`,
`limit`, `order_by`, `count`, `value_map`, `text_search_nodes`, `vector_search_nodes`. Build traversals
through `hdsl` helpers first; touch raw `helixdb` names only via `parrot.knowledge.helix.client`'s
lazy import (never `import helixdb` at module top here).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                                   # line 697
    supports_attrs: bool = False                                            # line 716
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int        # line 744 (abstract)
    async def add_edges(self, edges: list[tuple]) -> int                    # line 747 (abstract)
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]  # line 750
    async def delete_page(self, concept_id: str) -> bool                    # line 758
    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None  # line 761
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]  # line 765
    async def list_pages(self, category=None, limit=100, origin=None) -> list[dict[str, Any]]  # line 768
    async def search_fts(self, query: str, category=None, limit: int = 10) -> list[dict[str, Any]]  # line 776
    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]  # line 779
    async def neighbors(self, concept_id: str, rel=None, direction: str = "both") -> list[dict[str, Any]]  # line 782
    async def dump_pages(self) -> list[dict[str, Any]]                      # line 790
    async def dump_edges(self) -> list[dict[str, Any]]                      # line 793
    async def stats(self) -> dict[str, Any]                                 # line 796
    async def orphan_sources(self) -> list[str]                             # line 800
    async def broken_edges(self) -> list[dict[str, Any]]                    # line 803
    async def rebuild_index(self) -> dict[str, Any]                         # line 805 (concrete default)
    async def index_drift(self) -> dict[str, int]                           # line 815 (concrete default)
    async def missing_bodies(self) -> list[str]                             # line 820
    def _assert_writable(self) -> None                                      # line 881 (no-op hook)
class WikiPageRecord(BaseModel):  # line 433 — concept_id, node_id, title, category, summary, body, source_id,
                                  #   token_count, origin, asserted_by, updated_at, content_hash, attrs (lines 472-484)
# SQLite parity references (row shapes to copy key-for-key):
#   SQLiteWikiStore._upsert_pages_conn  :1758  (created_at kept, updated_at = p.updated_at or now, token_count or estimate_tokens(body))
#   _insert_edges_conn :1825 (3- or 4-tuples; provenance default "extracted")
#   replace_source_slice :1912 (preserves incoming edges from OTHER sources whose dst is re-inserted; drops attrs,
#     embeddings, edges touching old ids, symbols of the source) ; delete_page :2003
#   get_page :2390 (falls back to node_id; cols concept_id,node_id,title,category,summary,source_id,token_count,
#     created_at,updated_at,origin,asserted_by,content_hash[,body] + "attrs")
#   list_pages :2421 (stub cols, ORDER BY updated_at DESC) ; search_fts :2459 (category=None excludes "archive";
#     cols concept_id,node_id,title,category,summary,source_id,token_count,score) ; search_vector :2510
#   neighbors :2552 (concept_id, rel, provenance, title, category, summary, token_count, direction "out"|"in")
#   dump_pages :2595 (ORDER BY concept_id; incl. body, created_at, updated_at, content_hash) ; dump_edges :2609 (src,dst,rel ordered)
#   stats :2615 (pages, edges, sources, embeddings, symbols, total_tokens, categories, attrs_pages)
#   orphan_sources :2738 ; broken_edges :2748 (dst neither page nor source) ; missing_bodies :2758 (body == "")
#   rebuild_index :2764 ; index_drift :2782
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]   # line 76 (contextmanager, flock on store_dir/"wiki.lock")
# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py — server-backend precedent:
class ArangoDBWikiStore(BaseWikiStore):   # line 137 ; read_only :201 ; _assert_writable :205 ; initialize :260 ; close :475
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.helix_store`~~ — created by this task.
- ~~`BaseWikiStore.initialize()` / `close()`~~ — not on the base class; concrete backends define them.
- ~~`g().upsert(...)` / any HelixDB upsert op~~ — emulate via `hdsl.upsert_node_entries` (conditional entries).
- ~~A unique EDGE index in HelixDB~~ — dedupe with `hdsl.find_or_add_edge_entries` (multigraph).
- ~~`AsyncClient.graph()`, `/v2/cypher`, `SearchConsistency`~~ — not used / not available in 0.3.4.
- ~~`HelixWikiStore.sqlite_settings()` / `checkpoint()`~~ — SQLite-only maintenance; not part of `BaseWikiStore`.
- ~~`resolve_helix_params`~~ in this task — TASK-4379 owns it; the factory takes resolved kwargs.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_helix_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SCHEMA_VERSION",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#estimate_tokens",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py#ArangoDBWikiStore"
  ]
}
```

---

## Implementation Notes

### Data model (decided here — every later wiki-plane task depends on it)
- **Page** node, unique key `concept_id`; equality `node_id`, `category`, `source_id`, `origin`, `stub`;
  text property `search_text` (`title + "\n" + summary + "\n" + body`, truncated to `body_max_chars`);
  vector prefix `embedding` (`embedding_<d>` + `embedding_model`).
- **Edges** are native HelixDB edges labelled with the open-string `rel`, property `provenance`. An edge
  endpoint that is not an existing page is materialised as a **stub `Page`** (`stub=True`, no other
  props) so dangling targets survive exactly like SQLite (`broken_edges` lint exists for them). A later
  `upsert_pages` of that id flips `stub=False` on the same node (unique-key lookup), so incoming edges
  survive. Every page read/count/dump filters `stub == False`. `delete_page` drops the node with its
  incident edges (SQLite deletes edges touching it, `store.py:2019`).
- **PageAttr** node, unique key `attr_key = f"{concept_id}\x1f{key}"`; equality `concept_id`, `key`, `value`.
- **Symbol** node, unique `concept_id`; equality `rel_path`, `name`, `kind`, `language`, `source_id`;
  text `search_text` (name / qualname / doc / signature) — written by TASK-4377, dropped by
  `replace_source_slice` here.
- **Source** node, unique `source_id`; equality `source_uri`, `external_id` — written by TASK-4378,
  read by `orphan_sources`/`broken_edges`/`stats` here.
- **Meta** node, unique `key`; `ensure_plane` stamps `schema_version`; vector dims recorded by
  `ensure_vector_index` (TASK-4374).

### Key Constraints
- **One write batch per public write** (spec §7) — `upsert_pages`, `replace_source_slice`,
  `delete_page` include their attr/symbol/edge entries in the same `write_batch`. Reads that a write
  depends on (old ids of a slice, preserved incoming edges) are one read batch before the write.
- Row dicts match `SQLiteWikiStore` key-for-key (see the line references above).
- `search_fts`: `limit` clamped to 800 (log the clamp at debug); `category=None` excludes `"archive"`;
  `score` = HelixDB `$score` (higher is better). `search_vector`: zero vector → `[]`; no index of
  `len(embedding)` → `[]` + `self.logger.warning`; `score = 1 - $distance` (cosine, [-1, 1]) — AC10/AC18.
- `HelixWriteRejected` from the client propagates unchanged (AC11); never retry a batch blindly.
- Embedded guard (AC13): for `HelixMode.EMBEDDED` and not `read_only`, `initialize()` enters
  `wiki_write_lock(settings.root / settings.database)` through a `contextlib.ExitStack` and keeps it
  until `close()`. Not acquired ⇒ `HelixUnavailable` whose message names the database, says another
  process holds `wiki.lock`, and points to `helix_mode: server`. The lock lives in the Disk database
  directory, NOT `storage_dir`, so `wikitoolkit build` (which already holds `storage_dir/wiki.lock`)
  does not deadlock against itself. TASK-4375's spike file supplies the exact native error text to quote.
- `self.logger = logging.getLogger(__name__)`; Google docstrings; strict typing; 120 cols.

### References in Codebase
- `wiki/arango_store.py:137-480` — server-backend lifecycle (`initialize`/`close`/`read_only`).
- `wiki/store.py:1758-2800` — the SQLite semantics to mirror.

---

## Implementation Blueprint

### Steps (in order)
1. Re-verify TASK-4372/4373/4374 exports in the worktree (`grep -n "def \|^class " packages/ai-parrot/src/parrot/knowledge/helix/*.py`) — *why*: they are not on dev yet and their final names are the contract.
2. Write the module skeleton (constants, plane, class, lifecycle, factory) — *why*: every later wiki-plane task imports these names.
3. Implement the write surface, then reads, then search, then lint — *why*: tests for reads need writes.
4. Write `test_helix_store.py` and run it — *why*: AC1/AC10/AC18 parity evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` (CREATE) — part 1: plane + lifecycle
```python
"""HelixDB retrieval plane for one wiki (FEAT-670 M3)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any, ClassVar, Optional

from parrot.knowledge.helix import dsl as hdsl
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane, ensure_vector_index, known_vector_dimensions
from parrot.knowledge.helix.client import HelixClient, _sdk, open_helix_client
from parrot.knowledge.helix.errors import HelixUnavailable
from parrot.knowledge.helix.settings import HelixMode, HelixSettings, resolve_helix_settings
from parrot.knowledge.wiki.project import wiki_write_lock
from parrot.knowledge.wiki.store import SCHEMA_VERSION, BaseWikiStore, WikiPageRecord, estimate_tokens

MAX_SEARCH_LIMIT = hdsl.MAX_SEARCH_LIMIT
ATTR_KEY_SEP = "\x1f"
PAGE_STUB_COLS = ("concept_id", "node_id", "title", "category", "summary", "source_id", "token_count",
                  "updated_at", "origin", "asserted_by", "content_hash")

PAGE_LABEL = LabelSpec(label="Page", unique_key="concept_id", equality=["node_id", "category", "source_id", "origin", "stub"],
                       text_property="search_text", vector_property_prefix="embedding")
SYMBOL_LABEL = LabelSpec(label="Symbol", unique_key="concept_id",
                         equality=["rel_path", "name", "kind", "language", "source_id"], text_property="search_text")
SOURCE_LABEL = LabelSpec(label="Source", unique_key="source_id", equality=["source_uri", "external_id"])
META_LABEL = LabelSpec(label="Meta", unique_key="key")
PAGE_ATTR_LABEL = LabelSpec(label="PageAttr", unique_key="attr_key", equality=["concept_id", "key", "value"])

WIKI_PLANE = PlaneSchema(plane="wiki", schema_version=SCHEMA_VERSION,
                         labels=[PAGE_LABEL, SYMBOL_LABEL, SOURCE_LABEL, META_LABEL, PAGE_ATTR_LABEL], edge_labels=["*"])


def attr_key(concept_id: str, key: str) -> str:
    """Unique PageAttr key for one (page, attr) pair."""
    return f"{concept_id}{ATTR_KEY_SEP}{key}"


class HelixWikiStore(BaseWikiStore):
    """HelixDB retrieval plane for one wiki (server or embedded)."""

    supports_attrs: bool = True
    plane_schema: ClassVar[PlaneSchema] = WIKI_PLANE

    def __init__(self, settings: HelixSettings, wiki_name: str = "", *, read_only: bool = False,
                 body_max_chars: int = 16_000) -> None:
        self._settings = settings.model_copy(update={"read_only": read_only or settings.read_only})
        self._wiki_name = wiki_name
        self._body_max_chars = body_max_chars
        self._client: Optional[HelixClient] = None
        self._init_lock = asyncio.Lock()
        self._locks = contextlib.ExitStack()
        self.logger = logging.getLogger(__name__)

    @property
    def settings(self) -> HelixSettings:
        """Resolved connection settings of this plane."""
        return self._settings

    @property
    def read_only(self) -> bool:
        """Whether this store was opened strictly for reading."""
        return self._settings.read_only

    def _assert_writable(self) -> None:
        """Raise PermissionError on a read-only store."""
        if self.read_only:
            raise PermissionError(f"read-only HelixDB wiki store: {self._settings.database}")

    def _acquire_embedded_guard(self) -> None:
        """Hold <root>/<database>/wiki.lock for the store lifetime (embedded writers only, AC13)."""
        if self._settings.mode is not HelixMode.EMBEDDED or self.read_only:
            return
        assert self._settings.root is not None  # resolve_helix_settings guarantees it for EMBEDDED
        acquired = self._locks.enter_context(wiki_write_lock(Path(self._settings.root) / self._settings.database))
        if not acquired:
            self._locks.close()
            # FILL IN: quote the native error class recorded in sdd/state/FEAT-670/spike-embedded-two-writers.md — bounded by AC13
            raise HelixUnavailable(
                f"HelixDB embedded database {self._settings.database!r} is held by another process (wiki.lock); "
                "use helix_mode: server for multi-process access"
            )

    async def initialize(self) -> None:
        """Open the client and bootstrap the plane once; idempotent and concurrency-safe."""
        if self._client is not None:
            return
        async with self._init_lock:
            if self._client is not None:
                return
            self._acquire_embedded_guard()
            try:
                client = await open_helix_client(self._settings)
                if not self.read_only:
                    await ensure_plane(client, self.plane_schema)
            except BaseException:
                self._locks.close()
                raise
            self._client = client

    async def _c(self) -> HelixClient:
        """Return the open client, initializing lazily."""
        await self.initialize()
        assert self._client is not None
        return self._client

    async def close(self) -> None:
        """Close the client and release the embedded guard."""
        client, self._client = self._client, None
        try:
            if client is not None:
                await client.close()
        finally:
            self._locks.close()
```
**Why this shape**: lazy `initialize()` + `_c()` mirrors `ArangoDBWikiStore` and spec §7 "Bootstrap, not
migration"; `plane_schema` as a ClassVar lets `HelixLedgerStore`/`HelixSchemaStore` (TASK-4381/4382)
bootstrap their own label set without overriding `initialize`. Read-only stores never issue DDL.

### `helix_store.py` — part 2: write surface (append to the class)
```python
    def _search_text(self, page: WikiPageRecord) -> str:
        """Top-level BM25 text: title + summary + body, truncated to body_max_chars (AC11)."""
        return f"{page.title}\n{page.summary}\n{page.body}"[: self._body_max_chars]

    def _page_props(self, page: WikiPageRecord, now: str) -> dict[str, Any]:
        """Property map of one Page node (SQLite _upsert_pages_conn parity, store.py:1758)."""
        return {
            "concept_id": page.concept_id, "node_id": page.node_id, "title": page.title, "category": page.category,
            "summary": page.summary, "body": page.body, "source_id": page.source_id,
            "token_count": page.token_count or estimate_tokens(page.body), "updated_at": page.updated_at or now,
            "origin": page.origin, "asserted_by": page.asserted_by, "content_hash": page.content_hash,
            "search_text": self._search_text(page), "stub": False,
        }

    def _add_page_entries(self, batch: Any, pages: list[WikiPageRecord], now: str) -> None:
        """Append upsert entries for pages + replacement PageAttr entries (one batch)."""
        for i, page in enumerate(pages):
            hdsl.upsert_node_entries(batch, f"p{i}", "Page", "concept_id", self._page_props(page, now))
            # FILL IN: created_at only on insert (var_empty branch) — bounded by SQLite parity store.py:1758
            # FILL IN: drop PageAttr where concept_id == page.concept_id, then add one PageAttr per page.attrs item
            #          with attr_key(concept_id, k) — bounded by WikiPageRecord.attrs contract (store.py:466)

    def _add_edge_entries(self, batch: Any, edges: list[tuple], prefix: str) -> None:
        """Find-or-add rel-labelled edges; missing endpoints become stub Pages."""
        for i, edge in enumerate(edges):
            src, dst, rel = edge[0], edge[1], edge[2]
            provenance = edge[3] if len(edge) > 3 else "extracted"
            # FILL IN: resolve-or-stub src/dst vars (upsert_node_entries with {"concept_id": x, "stub": True} only on
            #          the var_empty branch) then hdsl.find_or_add_edge_entries(batch, f"{prefix}{i}", s, d, rel,
            #          {"provenance": provenance}) — bounded by spec §2 "Edges" + §7 multigraph risk

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        """Insert or update pages (and their attrs) in one atomic batch."""
        self._assert_writable()
        if not pages:
            return 0
        client = await self._c()
        batch = _sdk().write_batch()
        self._add_page_entries(batch, pages, _now_iso())
        await client.write(batch, query_name="wiki.upsert_pages")
        return len(pages)

    async def add_edges(self, edges: list[tuple]) -> int:
        """Insert typed edges (3- or 4-tuples), deduped on (src, dst, rel)."""
        self._assert_writable()
        if not edges:
            return 0
        client = await self._c()
        batch = _sdk().write_batch()
        self._add_edge_entries(batch, edges, "e")
        await client.write(batch, query_name="wiki.add_edges")
        return len(edges)

    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]:
        """Atomically replace all pages/edges/attrs/embeddings/symbols derived from one source."""
        self._assert_writable()
        edges = edges or []
        client = await self._c()
        new_ids = {p.concept_id for p in pages}
        # FILL IN: ONE read batch → old_ids (Page where source_id == source_id, stub False) and incoming edges
        #          (src, dst, rel, provenance) whose dst ∈ old_ids, src ∉ old_ids, dst ∈ new_ids — bounded by store.py:1957-1970
        old_ids: list[str] = []
        preserved: list[tuple] = []
        batch = _sdk().write_batch()
        # FILL IN: drop old Page nodes (edges go with them), their PageAttr nodes, Symbol where source_id == source_id
        self._add_page_entries(batch, pages, _now_iso())
        self._add_edge_entries(batch, list(edges), "e")
        self._add_edge_entries(batch, preserved, "k")
        await client.write(batch, query_name="wiki.replace_source_slice")
        return {"pages_deleted": len(old_ids), "pages_written": len(pages), "edges_written": len(edges)}
```
**Why**: the batch helpers keep "one batch per public write" mechanical; stub endpoints make HelixDB's
endpoint-bound edges behave like SQLite's free-form `edges` table. Batches come from `_sdk().write_batch()`
(TASK-4373's lazy SDK accessor) exactly as TASK-4374's bootstrap does.

### `helix_store.py` — part 3: delete, embedding, reads, search, lint, factory
```python
    async def delete_page(self, concept_id: str) -> bool:
        """Drop a page node (edges, attrs and embedding go with it)."""
        self._assert_writable()
        client = await self._c()
        # FILL IN: ONE batch: existence check var + drop Page(concept_id, stub False) + drop PageAttr(concept_id);
        #          return whether the page existed — bounded by store.py:2003 semantics
        raise NotImplementedError

    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None:
        """Lazy per-dimension vector index (resolved Q1), then set embedding_<d> + embedding_model."""
        self._assert_writable()
        client = await self._c()
        prop = await ensure_vector_index(client, "Page", "embedding", len(vector))
        # FILL IN: one batch: set_property(prop, vector) and ("embedding_model", model) on Page(concept_id) — AC10
        _ = prop

    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]:
        """Fetch by concept_id, falling back to node_id; includes "attrs" (store.py:2390)."""
        # FILL IN: read batch on concept_id then node_id (stub False), project PAGE_STUB_COLS + created_at
        #          (+ body); attach attrs from PageAttr(concept_id) as {key: value}
        raise NotImplementedError

    async def list_pages(self, category: Optional[str] = None, limit: int = 100,
                         origin: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Stub dicts (no body), newest updated_at first (store.py:2421)."""
        # FILL IN: n_with_label("Page") where stub False [+ category eq] [+ origin in] order_by updated_at desc limit
        raise NotImplementedError

    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:
        """BM25 over Page.search_text; category=None excludes "archive" (AC18); limit ≤ 800 (AC11)."""
        if not query.strip():
            return []
        if limit > MAX_SEARCH_LIMIT:
            self.logger.debug("search_fts: limit %d clamped to %d", limit, MAX_SEARCH_LIMIT)
            limit = MAX_SEARCH_LIMIT
        # FILL IN: hdsl.text_search("Page", "search_text", query, limit, projection=[...SQLite search_fts cols])
        #          → rows with "score" = $score; filter stub / category as in store.py:2459-2508
        raise NotImplementedError

    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        """Cosine search on embedding_<len>; score = 1 - $distance; [] + warning when no index (AC10/AC18)."""
        if not embedding or not any(embedding):
            return []
        client = await self._c()
        dims = await known_vector_dimensions(client, "Page")
        if len(embedding) not in dims:
            self.logger.warning("search_vector: no Page vector index of dimension %d (known: %s)", len(embedding), dims)
            return []
        # FILL IN: hdsl.vector_search("Page", f"embedding_{len(embedding)}", embedding, min(limit, 800), projection=[...])
        #          → stub dicts (concept_id,node_id,title,category,summary,source_id,token_count) + score = 1 - $distance
        raise NotImplementedError

    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]:
        """Edge-adjacent ids with rel/provenance/direction + target stub (store.py:2552)."""
        # FILL IN: out_e / in_e from Page(concept_id) [label == rel]; row keys concept_id, rel, provenance, title,
        #          category, summary, token_count (None for stub targets), direction "out"|"in"
        raise NotImplementedError

    async def dump_pages(self) -> list[dict[str, Any]]:
        """Every non-stub page WITH body, ordered by concept_id (store.py:2595)."""
        raise NotImplementedError  # FILL IN: bounded by store.py:2595 column list

    async def dump_edges(self) -> list[dict[str, Any]]:
        """Every edge as {src, dst, rel}, ordered by (src, dst, rel) (store.py:2609)."""
        raise NotImplementedError  # FILL IN: sort client-side if the DSL cannot order edges

    async def stats(self) -> dict[str, Any]:
        """pages, edges, sources, embeddings, symbols, total_tokens, categories, attrs_pages (store.py:2615)."""
        raise NotImplementedError  # FILL IN: counts in ONE read batch; stub pages excluded

    async def orphan_sources(self) -> list[str]:
        """Source ids with no non-stub Page whose source_id matches."""
        raise NotImplementedError  # FILL IN: bounded by store.py:2738

    async def broken_edges(self) -> list[dict[str, Any]]:
        """Edges whose dst is a stub page AND not a Source id (store.py:2748)."""
        raise NotImplementedError  # FILL IN

    async def missing_bodies(self) -> list[str]:
        """Non-stub pages whose body == ""."""
        raise NotImplementedError  # FILL IN

    async def rebuild_index(self) -> dict[str, Any]:
        """Re-run ensure_plane + every known vector index; dedupe (src, dst, rel) edges; re-stamp schema_version."""
        self._assert_writable()
        client = await self._c()
        report = await ensure_plane(client, self.plane_schema)
        rebuilt = [f"text:{spec.label}" for spec in self.plane_schema.labels if spec.text_property]
        for dim in await known_vector_dimensions(client, "Page"):
            rebuilt.append(f"vector:Page:{await ensure_vector_index(client, 'Page', 'embedding', dim)}")
        # FILL IN: drop duplicate edges sharing (src, dst, rel) keeping one — bounded by spec §7 "Cross-client edge races"
        self.logger.debug("rebuild_index: %s", report)
        return {"rebuilt": rebuilt}

    async def index_drift(self) -> dict[str, int]:
        """{"duplicate_edges": n} when (src, dst, rel) repeats; {} when clean."""
        raise NotImplementedError  # FILL IN: count duplicates from dump_edges-shaped read


def _now_iso() -> str:
    """ISO-8601 UTC now (same format as wiki/store.py:_now_iso)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def helix_wiki_store_factory(*, storage_dir: Path | None = None, wiki_name: str = "", **kwargs: Any) -> HelixWikiStore:
    """Factory the FEAT-540 built-in WikiBackendSpec row points at (lazy module path).

    kwargs: ``settings`` (a HelixSettings) or ``database`` / ``credentials_env`` / ``mode``; plus ``read_only``,
    ``body_max_chars``. Default database is ``wiki_<wiki_name>``.
    """
    settings = kwargs.get("settings")
    if settings is None:
        settings = resolve_helix_settings(
            database=kwargs.get("database") or f"wiki_{wiki_name or 'default'}",
            credentials_env=kwargs.get("credentials_env", "HELIXDB"),
            mode=kwargs.get("mode"),
            storage_dir=Path(storage_dir) if storage_dir is not None else None,
            read_only=bool(kwargs.get("read_only", False)),
        )
    return HelixWikiStore(settings, wiki_name=wiki_name, read_only=bool(kwargs.get("read_only", False)),
                          body_max_chars=int(kwargs.get("body_max_chars", 16_000)))
```
**Why**: method bodies are DSL op-trees whose exact chaining depends on TASK-4374's helper API, so they
are FILL IN; every bound (columns, ordering, archive rule, score scale, clamp) is fixed above. Every
`raise NotImplementedError` here must be replaced — the final file contains none. Compare `_now_iso`
with `wiki/store.py:312` and import it instead if you prefer (it is module-private; copying is fine).

### FILL IN checklist
- [ ] `_acquire_embedded_guard` message — quote the spike's native error; bounded by AC13
- [ ] `_add_page_entries` — created_at on insert only; PageAttr replace; bounded by `store.py:1758,1808`
- [ ] `_add_edge_entries` — stub endpoints + find-or-add; bounded by spec §2 Edges
- [ ] `replace_source_slice` — read old ids + preserved edges, drop slice + symbols; bounded by `store.py:1912-2001`
- [ ] `delete_page`, `upsert_embedding`, `get_page`, `list_pages`, `search_fts`, `search_vector`, `neighbors`
- [ ] `dump_pages`, `dump_edges`, `stats`, `orphan_sources`, `broken_edges`, `missing_bodies`, `index_drift`, edge dedupe in `rebuild_index`

---

## Acceptance Criteria

- [ ] AC1 (partial — abstract surface): every `BaseWikiStore` abstract method behaves like `SQLiteWikiStore` on embedded InMemory (`test_helix_store.py`).
- [ ] AC10: vectors indexed lazily per dimension; query with no matching dimension returns `[]` + warning.
- [ ] AC11: `search_fts` clamps `limit` to 800; `search_text` truncated to `body_max_chars`; `HelixWriteRejected` propagates.
- [ ] AC13 (store half): `helix_mode=embedded` refused while another holder has `<root>/<database>/wiki.lock`, message points to server mode.
- [ ] AC18: `search_fts(category=None)` excludes `archive`; `search_vector` score = `1 - $distance` ∈ [-1, 1]; zero vector → `[]`.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` clean; no `import helixdb`/`httpx` in this module.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_helix_store.py
import uuid

import pytest

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")

from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.wiki.helix_store import HelixWikiStore, helix_wiki_store_factory
from parrot.knowledge.wiki.store import WikiPageRecord


@pytest.fixture
async def helix_store():
    # tests/knowledge/helix/conftest.py fixtures are NOT visible from tests/knowledge/wiki — build settings inline.
    store = HelixWikiStore(HelixSettings(mode=HelixMode.MEMORY, database=f"test_{uuid.uuid4().hex}"), wiki_name="t")
    await store.initialize()
    yield store
    await store.close()


def _p(cid, body="b", category="concept", source_id=None, **kw):
    return WikiPageRecord(concept_id=cid, title=cid, body=body, category=category, source_id=source_id, **kw)


async def test_upsert_get_list_roundtrip(helix_store): ...          # get_page keys == SQLite keys incl. "attrs"; node_id fallback
async def test_edges_dedupe_and_neighbors(helix_store): ...         # same (src,dst,rel) twice → one edge; direction labels
async def test_dangling_edge_is_broken_until_page_exists(helix_store): ...  # stub dst → broken_edges; upsert page → not broken, edge kept
async def test_replace_source_slice_preserves_incoming(helix_store): ...    # SQLite store.py:1912 semantics; symbols of source dropped
async def test_delete_page_drops_edges_and_attrs(helix_store): ...
async def test_search_fts_archive_default_and_clamp(helix_store): ...       # AC18 + limit 5000 → ≤ 800
async def test_search_vector_lazy_dims_and_score_scale(helix_store): ...    # dims 3 and 5; wrong dim → [] + caplog warning; zero vec → []
async def test_dump_stats_lint(helix_store): ...                            # dump order, stats keys, missing_bodies, orphan_sources
async def test_read_only_refuses_writes(): ...                              # PermissionError, no DDL
async def test_factory_default_database(): ...                              # helix_wiki_store_factory(wiki_name="x", mode="memory") → database "wiki_x"
async def test_embedded_guard_refuses_second_holder(tmp_path): ...          # hold wiki_write_lock(root/db) → HelixUnavailable mentioning "server"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`)
2. **Read the spec** at the path listed above (§2 data-model mapping, §3 M3, §7)
3. **Check dependencies** — TASK-4374 must be `"done"` in `sdd/tasks/index/helixdb-provider.json`
4. **Verify the Codebase Contract** — especially the TASK-4372/4373/4374 names; if they differ, update this contract first
5. **Update status** in the per-spec index → `"in-progress"` and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`; leave no `NotImplementedError`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4376 helixdb-provider verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
