# TASK-4389: PageIndex generation-based HelixDB projection

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 9, §9 S6, AC8, AC22)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4374
**Assigned-to**: unassigned

---

## Context

PageIndex stays canonical on disk (JSON tree + markdown bodies + `.npy` matrix). With a projection configured,
`HybridPageIndexSearch` serves its BM25 and vector legs from HelixDB (`TreeNode` + `CHILD_OF`). Because
`splice_subtree()` renumbers node ids tree-wide before `_persist()` (design research S6), the projection is
**generation-based**: `_persist()` is the single trigger, each projection replaces the tree's whole node set in one
atomic write batch stamped with a monotonic `generation` (Meta `pageindex_gen:<tree>`), and a search whose expected
generation does not match falls back to the legacy `bm25s`/numpy path.

---

## Scope

- Create `pageindex/helix_projection.py` with `PageIndexHelixProjection` (spec §3 M9 surface) and a `PAGEINDEX_PLANE`
  `PlaneSchema`.
- `hybrid_search.py`: new ctor kwarg `helix_projection`, `set_helix_generation()`, and async delegation in `search()`
  for the BM25 and vector legs; without a projection the code path is byte-identical.
- `toolkit.py`: new ctor kwarg `helix_settings`; build the projection, hand it to every `HybridPageIndexSearch`,
  and schedule `project_generation` from `_persist()`.
- Tests in `tests/knowledge/pageindex/test_helix_projection.py`.

**NOT in scope**: BookStore (TASK-4390); any change to `JSONTreeStore`, `NodeContentStore`, `NodeEmbeddingStore`,
`tree_ops.py`; `mark_dirty()` semantics (spec: unchanged); a durable outbox.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/helix_projection.py` | CREATE | `PageIndexHelixProjection`, `PAGEINDEX_PLANE` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | ctor kwarg, generation setter, async delegation in `search()` |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `helix_settings` kwarg, projection wiring, `_persist` scheduling |
| `packages/ai-parrot/tests/knowledge/pageindex/test_helix_projection.py` | CREATE | ranking parity, delegation, generation fallback |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`.

### Verified Imports
```python
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch   # hybrid_search.py:52
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit              # toolkit.py (class, ctor :92-108)
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore    # embedding_store.py (load_tree_matrix :306)
from parrot.knowledge.pageindex.utils import get_nodes                       # imported by hybrid_search.py:31
# created by TASK-4372/4373/4374 (verify before use):
from parrot.knowledge.helix.settings import HelixSettings                    # .with_database(name)
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.bootstrap import PlaneSchema, LabelSpec, ensure_plane, ensure_vector_index
from parrot.knowledge.helix import dsl                                       # text_search, vector_search, upsert_node_entries, find_or_add_edge_entries
```

### Existing Signatures to Use
```python
# pageindex/hybrid_search.py
class HybridPageIndexSearch:                                       # :52
    def __init__(self, tree, adapter, reranker=None, model=None, default_bm25_k=20, content_loader=None,
                 embedding_store=None, embed_fn=None, use_vec_rank=False, use_embedding_walk=False)  # :73-85
    self._tree / self._embed_fn / self._embedding_store / self._default_bm25_k   # :86-95
    def mark_dirty(self) -> None                                   # :119 (unchanged)
    def _flatten_corpus(self) -> tuple[list[str], list[str]]       # :145 — "title summary body" per node (body ≤ _BM25_TEXT_LIMIT=4000)
    def _bm25_rank(self, query: str, top_k: int) -> list[str]      # :177 — SYNC
    def _vec_rank(self, query: str, top_k: int) -> list[str]       # :199 — SYNC
    async def search(self, query, top_k=10, use_bm25=True, use_llm_walk=True, use_vec=False,
                     use_embedding_walk=None, rerank=False) -> list[dict]   # :288
        bm25_ranking = self._bm25_rank(query, self._default_bm25_k)        # :341
        vec_ranking = await asyncio.to_thread(self._vec_rank, query, top_k)  # :346

# pageindex/toolkit.py
logger = logging.getLogger("parrot.knowledge.pageindex.toolkit")  # :47 (module logger; no self.logger in this class)
def __init__(..., use_vec_rank: bool = False, use_embedding_walk: bool = False, **kwargs: Any)  # :92-108
self._store = JSONTreeStore(storage_dir)                           # :114
self._trees: dict[str, dict[str, Any]]                             # :162
self._search: dict[str, HybridPageIndexSearch]                     # :166
engine = HybridPageIndexSearch(... use_embedding_walk=self._use_embedding_walk,)   # :222-233
def _persist(self, tree_name: str) -> None                         # :237 — SYNC; calls engine.mark_dirty() :248
self._content_store.loader_for(tree_name) -> Callable[[str], Optional[str]]   # content_store.py:212

# pageindex/embedding_store.py
def load_tree_matrix(self, tree_name: str) -> Optional[tuple[np.ndarray, list[str]]]  # :306
```

### Does NOT Exist
- ~~`HybridPageIndexSearch._bm25_rank` being async~~ — both legs are sync; delegation goes through new async helpers called from `search()`.
- ~~`PageIndexToolkit.logger` / `self.logger`~~ — use module `logger`.
- ~~`HybridPageIndexSearch.set_helix_generation` / `helix_projection`~~ — created here.
- ~~A HelixDB upsert op~~ — whole-tree replace = drop every `TreeNode` of the tree + add, one write batch.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/helix_projection.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_helix_projection.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch.search",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch._bm25_rank",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch._vec_rank",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._persist",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py#NodeEmbeddingStore.load_tree_matrix"
  ]
}
```

---

## Implementation Notes

### Spec drift
- Spec §3 M9 says "`_bm25_rank` :177 and `_vec_rank` :199 delegate". They are **synchronous** and the projection is
  async, so delegation is done in `search()` through two new async helpers `_bm25_rank_async` / `_vec_rank_async` that
  try the projection and otherwise call the unchanged sync method exactly as today (`_bm25_rank` inline,
  `_vec_rank` via `asyncio.to_thread`). `_bm25_rank` / `_vec_rank` themselves are **not** edited.
- `_persist()` is synchronous: projection is scheduled with `loop.create_task` when a loop is running (strong refs in
  `self._helix_tasks`); with no running loop it is skipped and logged at debug (the next persist re-projects the whole tree).

### Generation protocol (decided here)
1. `_persist(tree)` → `engine.set_helix_generation(None)` immediately (searches fall back while projecting).
2. The task (serialised per tree by an `asyncio.Lock`) computes `gen = (await projection.current_generation(tree) or 0) + 1`,
   calls `project_generation(...)`, and on success `engine.set_helix_generation(gen)`.
3. A failure is logged once (`logger.warning`) and leaves the engine on the legacy path.
4. `bm25_rank`/`vector_rank` return `None` when the stored Meta generation ≠ the expected one.

### Key Constraints
- No projection ⇒ byte-identical behaviour (AC8); do not reorder `search()` statements outside the two legs.
- One write batch per `project_generation` (spec §7 "one batch per public write"); `search_text` = same text as
  `_flatten_corpus` (title + summary + body[:4000]) so ranking parity is set-equality (AC8, spec §7 BM25 analyzer note).
- `TreeNode` unique key `f"{tree_name}:{node_id}"`; edges `CHILD_OF` child→parent; embedding property via
  `ensure_vector_index(client, "TreeNode", "embedding", dim)` from the `.npy` matrix rows (`node_order` aligns rows).
- Database: `settings.with_database(f"pageindex_{<storage-dir name>}")` decided by the toolkit.

### References in Codebase
- `pageindex/hybrid_search.py:145-161` — corpus text to mirror.
- `pageindex/toolkit.py:249-252` — best-effort projection precedent (`_project_okf_sidecars`: errors logged, never raised).

---

## Implementation Blueprint

### Steps (in order)
1. Create `helix_projection.py` — *why*: the projection is self-contained and testable on helix-memory.
2. Add the ctor kwarg + async legs in `hybrid_search.py` — *why*: AC8 delegation with fallback.
3. Wire `toolkit.py` — *why*: `_persist` is the single generation trigger (S6).
4. Tests, then validation commands.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/helix_projection.py` (CREATE)
```python
"""Generation-based HelixDB projection of PageIndex trees (FEAT-670 M9, design research S6)."""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Optional

from parrot.knowledge.helix import dsl
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane, ensure_vector_index
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.settings import HelixSettings

if TYPE_CHECKING:
    import numpy as np

PAGEINDEX_PLANE = PlaneSchema(
    plane="pageindex",
    schema_version="1",
    labels=[
        LabelSpec(label="TreeNode", unique_key="key", equality=["tree_name", "node_id", "generation"],
                  text_property="search_text", vector_property_prefix="embedding"),
        LabelSpec(label="Meta", unique_key="key"),
    ],
    edge_labels=["CHILD_OF"],
)


class PageIndexHelixProjection:
    """Generation-based projection of one PageIndex storage dir into HelixDB."""

    def __init__(self, settings: HelixSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self._client: Optional[HelixClient] = None

    async def _ensure(self) -> HelixClient:
        """Open the client and bootstrap the plane once per instance."""
        if self._client is None:
            client = await open_helix_client(self.settings)
            await ensure_plane(client, PAGEINDEX_PLANE)
            self._client = client
        return self._client

    async def close(self) -> None:
        """Close the client (idempotent)."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def project_generation(
        self,
        tree_name: str,
        generation: int,
        tree: dict[str, Any],
        body_loader: Callable[[str], Optional[str]],
        matrix: "np.ndarray | None" = None,
        node_order: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """ONE write batch: drop every TreeNode of ``tree_name``, add nodes/edges/embeddings, set Meta pageindex_gen."""
        client = await self._ensure()
        # FILL IN: walk tree["structure"] (utils.get_nodes) → TreeNode props {key, tree_name, node_id, generation, title,
        #   search_text=f"{title} {summary} {body[:4000]}".strip()}; CHILD_OF child→parent; when matrix/node_order given,
        #   ensure_vector_index(client, "TreeNode", "embedding", matrix.shape[1]) BEFORE the batch and set embedding_<d>;
        #   drop old nodes + add + Meta upsert in one dsl write batch via client.write(..., query_name="pageindex.project")
        #   — bounded by spec §7 "one batch per public write" and AC22
        raise NotImplementedError

    async def current_generation(self, tree_name: str) -> int | None:
        """Generation stored on Meta ``pageindex_gen:<tree>`` or ``None``."""
        # FILL IN: dsl.lookup_by_key("Meta", "key", f"pageindex_gen:{tree_name}") read — bounded by spec §3 M9
        raise NotImplementedError

    async def drop_tree(self, tree_name: str) -> int:
        """Remove every TreeNode (and its edges) of ``tree_name`` plus its Meta; returns nodes dropped."""
        # FILL IN: one write batch — bounded by spec §3 M9
        raise NotImplementedError

    async def bm25_rank(self, tree_name: str, generation: int, query: str, top_k: int) -> list[str] | None:
        """Node ids by BM25, or ``None`` when the stored generation differs (caller falls back)."""
        if await self.current_generation(tree_name) != generation:
            return None
        # FILL IN: dsl.text_search("TreeNode", "search_text", query, limit=min(top_k * 4, 800), ["node_id", "tree_name"])
        #   filtered to tree_name, first top_k node_ids in score order — bounded by AC8 (top-k set equality)
        raise NotImplementedError

    async def vector_rank(
        self, tree_name: str, generation: int, query_vector: Sequence[float], top_k: int
    ) -> list[str] | None:
        """Node ids by cosine distance, or ``None`` on generation mismatch / no index of that dimension."""
        if await self.current_generation(tree_name) != generation:
            return None
        # FILL IN: dsl.vector_search on embedding_<len(query_vector)>; [] → None so the numpy leg runs — bounded by AC8, AC10
        raise NotImplementedError
```
**Why this shape**: the surface is the spec §3 M9 skeleton verbatim plus `close()`; the generation check lives
inside the rank methods so the caller's only decision is `None` ⇒ legacy.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` (MODIFY)
```python
# Edit 1 — occurrences: 1 (verified: grep -c -F '        use_embedding_walk: bool = False,' hybrid_search.py) — line 84
# AFTER that line insert the kwarg:
        helix_projection: Optional["PageIndexHelixProjection"] = None,
# and in the TYPE_CHECKING block (line 33-34, after `from .embedding_store import NodeEmbeddingStore`):
    from .helix_projection import PageIndexHelixProjection

# Edit 2 — `        self._dirty = True` occurs 2 times (:99, :127); use the ctor context (unique):
#         self._corpus_node_ids: list[str] = []
#         self._dirty = True
# AFTER those two lines (ctor, line 99) insert:
        self._helix_projection = helix_projection
        self._helix_generation: Optional[int] = None
        self._helix_fallback_logged = False

# Edit 3 — new methods; insert BEFORE `    def _bm25_rank(self, query: str, top_k: int) -> list[str]:` (occurrences: 1, line 177):
    def set_helix_generation(self, generation: Optional[int]) -> None:
        """Set the projection generation searches expect (``None`` ⇒ legacy legs)."""
        self._helix_generation = generation

    async def _projected(self, kind: str, query: str, top_k: int) -> Optional[list[str]]:
        """Projection ranking, or ``None`` to fall back (no projection, no generation, mismatch, error)."""
        projection, generation = self._helix_projection, self._helix_generation
        tree_name = self._tree.get("doc_name") or ""
        if projection is None or generation is None or not tree_name:
            return None
        try:
            if kind == "bm25":
                ranked = await projection.bm25_rank(tree_name, generation, query, top_k)
            else:
                if self._embed_fn is None:
                    return None
                q_vecs = await asyncio.to_thread(self._embed_fn, [query])
                ranked = await projection.vector_rank(tree_name, generation, list(map(float, q_vecs[0])), top_k)
        except Exception as exc:  # noqa: BLE001 — projection is best-effort; canonical files win
            ranked = None
            if not self._helix_fallback_logged:
                logger.warning("helix projection %s leg failed for %s: %s", kind, tree_name, exc)
        if ranked is None and not self._helix_fallback_logged:
            logger.info("helix projection unavailable for %s (generation %s); using legacy legs", tree_name, generation)
            self._helix_fallback_logged = True
        return ranked

    async def _bm25_rank_async(self, query: str, top_k: int) -> list[str]:
        ranked = await self._projected("bm25", query, top_k)
        return ranked if ranked is not None else self._bm25_rank(query, top_k)

    async def _vec_rank_async(self, query: str, top_k: int) -> list[str]:
        ranked = await self._projected("vec", query, top_k)
        return ranked if ranked is not None else await asyncio.to_thread(self._vec_rank, query, top_k)

# Edit 4 — occurrences: 1 each (lines 341, 346):
#   `            bm25_ranking = self._bm25_rank(query, self._default_bm25_k)`
#   → `            bm25_ranking = await self._bm25_rank_async(query, self._default_bm25_k)`
#   `            vec_ranking = await asyncio.to_thread(self._vec_rank, query, top_k)`
#   → `            vec_ranking = await self._vec_rank_async(query, top_k)`
```
**Why**: with `helix_projection=None`, `_projected` returns `None` before any await-side effect, and the legacy
calls are the same expressions as before (AC8 byte-identical baseline).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# Edit 1 — occurrences: 1 (verified: grep -c -F '        use_embedding_walk: bool = False,' toolkit.py) — line 106
# AFTER it insert:
        helix_settings: Optional["HelixSettings"] = None,
# (add `from typing import TYPE_CHECKING` handling: `if TYPE_CHECKING: from parrot.knowledge.helix.settings import HelixSettings`)

# Edit 2 — occurrences: 1 (verified: grep -c -F '        self._store = JSONTreeStore(storage_dir)' toolkit.py) — line 114
# AFTER it insert:
        self._helix_projection = None
        self._helix_locks: dict[str, asyncio.Lock] = {}
        self._helix_tasks: set[asyncio.Task] = set()
        if helix_settings is not None:
            from .helix_projection import PageIndexHelixProjection  # lazy: no helix import unless configured

            # FILL IN: database name = f"pageindex_{Path(storage_dir).name}" via helix_settings.with_database(...)
            #   — bounded by spec §2 "one database per plane" and projections-are-opt-in (§7)
            self._helix_projection = PageIndexHelixProjection(helix_settings)

# Edit 3 — in the engine construction, occurrences: 1 (`                use_embedding_walk=self._use_embedding_walk,` inside HybridPageIndexSearch(...), line 232;
#   verify with grep -c -F; if >1 quote the `content_loader=self._content_store.loader_for(tree_name),` line above it)
# AFTER it insert:
                helix_projection=self._helix_projection,

# Edit 4 — occurrences: 1 (verified: grep -c -F '        self._project_okf_sidecars(tree_name, tree)' toolkit.py) — line 252, last line of _persist
# AFTER it insert:
        self._schedule_helix_projection(tree_name, tree)

# Edit 5 — new method, insert right after `_persist` (before `def _project_okf_sidecars`):
    def _schedule_helix_projection(self, tree_name: str, tree: dict[str, Any]) -> None:
        """Re-project the whole tree as a new generation (S6); best-effort, never raises."""
        if self._helix_projection is None:
            return
        engine = self._search.get(tree_name)
        if engine is not None:
            engine.set_helix_generation(None)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("helix projection of %s skipped: no running loop", tree_name)
            return
        task = loop.create_task(self._project_tree(tree_name, tree))
        self._helix_tasks.add(task)
        task.add_done_callback(self._helix_tasks.discard)

    async def _project_tree(self, tree_name: str, tree: dict[str, Any]) -> None:
        lock = self._helix_locks.setdefault(tree_name, asyncio.Lock())
        async with lock:
            # FILL IN: gen = (await current_generation or 0) + 1; matrix/node_order from self._embedding_store.load_tree_matrix
            #   when present; await project_generation(tree_name, gen, tree, self._content_store.loader_for(tree_name), ...);
            #   on success set the engine generation; on exception logger.warning and leave None — bounded by AC22
            raise NotImplementedError
```

### FILL IN checklist
- [ ] `helix_projection.py::project_generation` / `current_generation` / `drop_tree` / `bm25_rank` / `vector_rank` — bounded by AC8, AC22, AC10.
- [ ] `toolkit.py` database naming — bounded by spec §2.
- [ ] `toolkit.py::_project_tree` — bounded by AC22.
- [ ] Tests below — bounded by AC8/AC22.

---

## Acceptance Criteria

- [ ] AC8: with a projection, BM25 and vector legs return the same top-k **set** as the `bm25s`/numpy path on the fixture tree; without one, `search()` output is byte-identical (existing `test_hybrid_search.py` passes unchanged).
- [ ] AC22: generation-based; mismatch ⇒ `bm25_rank` returns `None` and the legacy leg runs; a splice + `_persist` re-projects the whole tree.
- [ ] No `helixdb` import when `helix_settings` is not passed.
- [ ] `ruff check` clean on the three source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_helix_projection.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_helix_projection.py
"""FEAT-670 M9 — PageIndex projection (embedded InMemory)."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")

from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.pageindex.helix_projection import PageIndexHelixProjection
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch


@pytest.fixture
def settings() -> HelixSettings:
    return HelixSettings(mode=HelixMode.MEMORY, database=f"test_{uuid.uuid4().hex}")


def _tree() -> dict:
    # same shape as tests/knowledge/pageindex/test_hybrid_search.py::_fixture_tree (doc_name "demo", nodes 0000..0003)
    ...


async def test_pageindex_projection_ranks(settings):
    """bm25_rank top-k set == HybridPageIndexSearch._bm25_rank top-k set for 3 queries."""


async def test_hybrid_search_delegates_when_projected(settings):
    """With projection + generation set, search(use_llm_walk=False) uses projection.bm25_rank (spy); without, the legacy leg."""


async def test_pageindex_generation_fallback(settings):
    """Stored gen 1, expected 2 → bm25_rank returns None and search() still returns legacy results."""


async def test_toolkit_persist_reprojects_whole_tree(tmp_path, settings):
    """PageIndexToolkit(helix_settings=…): create + splice + _persist → current_generation increments, no stale node ids."""
```
(Test bodies are the implementer's; the four names are fixed by spec §4.)

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`
2. **Read the spec** §3 M9 and §9 S6.
3. **Check dependencies** — TASK-4374 must be `done` in `sdd/tasks/index/helixdb-provider.json`; read its `dsl.py`/`bootstrap.py` signatures first (they are the contract you call).
4. **Verify the Codebase Contract** — re-run each `grep -c -F`; stop if a count changed.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — only the four listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4389 helixdb-provider verified`.
10. **Fill in the Completion Note**, then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
