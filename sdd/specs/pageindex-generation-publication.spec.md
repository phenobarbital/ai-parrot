---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — carried from sdd/proposals/pageindex-tree-optimizer.brainstorm.md (ai-parrot-tools is touched by later slices, not this one)
tags: [pageindex, tree-optimizer, generations, copy-on-write, bookstore, mcp]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-generation-publication.md]
  api_modules: [parrot.knowledge.pageindex.generation, parrot.knowledge.pageindex.locks]
---

# Feature Specification: PageIndex Generation Publication

**Feature ID**: FEAT-831
**Date**: 2026-11-06
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> First of the six slices of `sdd/proposals/pageindex-tree-optimizer.brainstorm.md`
> (revision 4). The next slices — `pageindex-segment-store`, `pageindex-layout-structure`,
> `pageindex-agentic-retrieval`, `pageindex-tree-optimizer`, `pageindex-local-mcp-toolkit` —
> all build on the publication path this spec introduces. Source paths below are relative
> to `packages/ai-parrot/src/parrot/` unless stated; line numbers were verified at `dev`
> @ `8b73aa8c88`.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

A PageIndex tree is one JSON file plus one markdown body per node, written by
`PageIndexToolkit` (`knowledge/pageindex/toolkit.py`). Every write today mutates the
cached tree dict in place, saves it with no check that the file on disk is still the
version it loaded, and writes body sidecars immediately, keyed by a `node_id` that
`reindex_node_ids` renumbers tree-wide on every splice. Concretely:

1. **Lost updates.** Nothing locks a tree. `_persist` (`toolkit.py:237`) saves
   unconditionally (`:244`); the on-disk signature is consulted only on read
   (`_load_tree`, `:203`). When two processes — an agent, the Bookstore CLI, the future
   local MCP server — write the same tree, the last writer silently discards the other's
   edit.
2. **Torn reads.** `_load_tree` hands every caller the same mutable dict (`:214`), and
   every mutator edits it in place (`tag_node :797-808`, `splice_subtree` in
   `insert_markdown :850`, `delete_node :1100`, `update_node :1255-1258`). A reader half-way
   through a request sees the edit another coroutine is making. `_batch` (`:392-400`)
   only defers the JSON save and persists in `finally`, so a failed `import_folder` still
   lands a half-mutated tree. Body sidecars are written before the tree JSON
   (`_save_node_markdown :1002` runs at `:851`, `_persist` at `:854`).
3. **A window without a live tree.** `rename_tree(overwrite=True)` (`:443-548`) moves the
   live JSON to a `--replaced-` backup before moving the staged one in (`:515-522`); a
   process loading between those two `os.replace` calls gets "tree does not exist". The
   backup is deleted as soon as the swap succeeds (`:534-540`), so a reader that loaded the
   old tree now reads the new bodies under old node ids.
4. **Best-effort projection.** `project_sidecars` raises (`okf/projection.py:97-156`) but
   `_project_okf_sidecars` swallows it (`toolkit.py:289-291`); a tree can be published with
   stale or missing OKF sidecars.
5. **Bodies keyed by an unstable id.** `<tree>/<node_id>.md` (`content_store.py:1-21`)
   must be re-keyed on every splice, which makes a copy-on-write generation as expensive
   as copying the tree. `NodeContentStore.save` is a plain `write_text` (`:115`), not an
   atomic replace.

Every later slice of the PageIndex upgrade — segment store, optimizer, agentic retrieval
with validated citations, the local MCP server — needs a write path where a reader keeps
one consistent generation for a whole request and a writer can never overwrite someone
else's edit. This spec builds that path once, for every write.

### Goals

- Every write to a tree (import, splice, delete, node and body updates, rename, future
  optimize) publishes a **generation**: the writer works on a copy, validates, writes every
  file durably, then switches the tree JSON atomically. Readers see either the complete old
  generation or the complete new one.
- A **per-tree writer lock that works across processes** serializes publication, and a
  **stale check** rejects a candidate built from a generation that is no longer live
  instead of overwriting it.
- **Bodies get a stable address** keyed by node identity (`concept_id`, assigned where it is
  missing) plus content hash, so a generation is one atomic JSON replace and nothing is
  remapped after `reindex_node_ids`.
- The existing **staging-tree swap** (`rename_tree`, Bookstore reindex) is extended, not
  replaced: no manifest, no window without a live tree, replaced generations retained for a
  **configurable grace period (one hour by default)** and removed by the existing age-based
  sweep. A failure before publication leaves the old generation active; crash recovery is
  the startup sweep.
- **Id-keyed indexes follow the generation** (BM25 corpus, embedding matrix and node order);
  content-addressed node vectors stay shared across generations.
- **OKF projection is strict** for a candidate: its failure aborts publication.
- Existing trees keep working unchanged until their first write; legacy `<node_id>.md`
  bodies remain readable.

### Non-Goals (explicitly out of scope)

- Segments, page/paragraph addresses, document revisions and read tools
  (`pageindex-segment-store`); the layout builder; the optimizer; the agentic stage and
  citations; the MCP template. This spec only gives them a safe write path.
- A generation manifest file or a transaction log — rejected in the brainstorm (revision 3):
  the tree JSON, already written with temp-file + `os.replace`, is the publication point.
- Multi-tree transactions. One generation is one tree.
- Changing the OKF sidecar format or making OKF sidecars generation-versioned: they are a
  derived, idempotent projection and stay written in place (see §7).
- Distributed locking across machines. The lock is a POSIX file lock on the shared
  `storage_dir`; trees on a filesystem without `fcntl` semantics are not supported.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:5d1f9e6def03e11e3cafa5368473a2878618a3f39a81e4414e0c068690798570 evaluation_digest=sha256:af04202ec87ca620a4ff90974b1105ddc23171c43e5a820f19f826db79b8a1f0 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

**Generation.** A generation is one published snapshot of a tree: the tree JSON plus the
body blobs it references. The tree JSON carries `generation: {"id": <int>,
"published_at": <ISO-8601>, "parent": <int|null>}`. The JSON file is the publication
point: `JSONTreeStore.save` already writes a temp file and `os.replace`s it
(`store.py:73-81`); this spec adds `fsync` before the replace so "durable" means durable.
No manifest, no log.

**Bodies by identity.** Node bodies stop living at `<tree>/<node_id>.md`. A body is an
immutable blob at `<tree>/bodies/<flat_concept_id>.<sha16>.md`, where `flat_concept_id`
is the node's `concept_id` flattened the way OKF sidecars already flatten it
(`toolkit.py:1172-1189`) and `sha16` is the first 16 hex chars of the SHA-256 of the
markdown. The node dict holds `body_ref: "<flat_concept_id>.<sha16>"`. A body change is a
new blob and a new `body_ref`, never an overwrite, so the old generation's references stay
valid for the grace period. `splice_subtree` already assigns a deterministic `concept_id`
to every node that lacks one (`tree_ops.py:56-86`, `:127`); this spec makes that
assignment unconditional for publication (a node without `concept_id` cannot have a body).
Legacy `<node_id>.md` and `<flat_concept_id>.md` sidecars stay readable: a node without
`body_ref` falls back to them.

**Copy-on-write transaction.** Every mutator runs inside
`async with self._write(tree_name) as txn`. The transaction records the loaded tree's
on-disk signature and generation id, deep-copies the tree, and hands the copy to the
mutator. Mutators keep their current shape (`splice_subtree`, `delete_node`, field edits)
but operate on `txn.tree`; bodies go through `txn.set_body(node, markdown)` and are staged
in memory. Nested `_write` calls on the same tree join the open transaction (this replaces
`_batch`, whose only user is `import_folder`, `toolkit.py:1067`).

**Publication** happens once, on transaction exit without an exception, under the per-tree
lock:

1. Acquire the exclusive cross-process lock `<storage_dir>/.locks/<tree_name>.lock`
   (`fcntl`, same pattern as `knowledge/wiki/repo_cache.py:50-95`, but raising
   `TreeLockTimeout` instead of yielding `False`).
2. **Stale check**: re-stat the JSON; if its signature differs from the one recorded at
   load, read the on-disk generation id; if it differs from the base generation, raise
   `StaleGenerationError`. Nothing is written.
3. Validate the candidate: every node has `concept_id`; every `body_ref` either exists on
   disk or is staged; names are valid.
4. Write staged body blobs atomically (temp + `fsync` + `os.replace`), then `fsync` the
   `bodies/` directory.
5. **Strict OKF projection**: when the tree is OKF-enriched (the existing rule at
   `toolkit.py:279`), run `project_sidecars` with the candidate; any exception aborts
   publication. Blobs written in step 4 become orphans the sweep removes.
6. Write the JSON with `generation.id = base + 1` (temp + `fsync` + `os.replace`).
7. Swap the in-process state: `_trees[tree_name] = candidate`, remember the new signature,
   build a **new** `HybridPageIndexSearch` for the candidate (the old engine stays alive
   for any reader still holding it), evict the content cache for the tree, drop
   `_okf_toolkits[tree_name]`.
8. Opportunistic sweep: delete blobs in `bodies/` and legacy `<node_id>.md` files that the
   live JSON does not reference and whose mtime is older than `generation_grace_s`
   (default 3600). Release the lock.

On any exception before step 6 the on-disk tree is untouched and the in-memory cache keeps
the old generation. On a crash between steps 4 and 6 the next publish or sweep removes the
orphan blobs. On a crash after step 6 the generation is complete by construction.

**Readers.** `_load_tree` keeps its signature-based reload (`toolkit.py:198-216`) and now
returns an object that is never mutated afterwards: a reader keeps the generation it loaded
for as long as it holds the dict. Bodies are resolved from the node the reader holds
(`body_ref`), so a reader on generation N reads generation N's blobs even after N+1 is
published. `get_tree` returns the cached dict unchanged (`:552`); its docstring states that
callers must not mutate it.

**Readers that key bodies by `node_id`** (revision 0.2). Besides the toolkit and
Bookstore, eleven call sites read bodies through `NodeContentStore.load(tree_name, key)`,
`has()` or `loader_for(tree_name)` with a `node_id` or flat concept id: `pageindex/loader.py:285`,
`pageindex/okf/bundle.py:324`, `pageindex/okf/migrate.py:285-287`, `pageindex/okf/tools.py:201`,
`graphindex/projection.py:230`, `wiki/ingest.py:627,877`, `contracts/library.py:1027`,
`manuals/library.py:364`, `lint/packs/okf.py:98`. They are not edited. Instead, when the
legacy file for a key is absent, `load`/`has`/`loader_for(tree_name)` resolve the key through
the **live** tree JSON (`<storage_dir>/<tree_name>.json`, the same directory the content store
already owns): `node_id` or flat concept id → node → `body_ref` → blob. The resolution index
is cached per tree and rebuilt when the JSON's `(st_mtime_ns, st_size)` changes. These callers
therefore keep exactly today's semantics (they read the live generation). Callers that must
stay on the generation they loaded — the toolkit's `retrieve` and `search_documents_scoped`
(`toolkit.py:651`, `:742`), the search engine and Bookstore's `read_section`
(`bookstore/library.py:374`) — use `load_node(tree_name, node)` with the node they hold.

The search engine is created per generation
(`_search_for`), with the BM25 corpus and the embedding matrix keyed by `tree_name` and
generation id; this also fixes `mark_dirty` invalidating embeddings by `doc_name`
(`hybrid_search.py:129`) instead of the tree name.

**Rename and swap.** `rename_tree(src, dst, overwrite=True)` becomes a publication of
`dst` from `src`'s candidate: under `dst`'s lock (and `src`'s), copy or hard-link `src`'s
blobs into `dst/bodies/` (names are unique by construction; existing names are skipped),
run strict OKF projection for `dst`, write `dst.json` from `src`'s tree with
`generation.id = dst.generation + 1` (atomic replace — **there is no moment without a
live `dst`**), then remove `src.json` and `src`'s directory. No `--replaced-` backup tree
is created: the replaced generation's blobs stay in `dst/bodies/` until the sweep.
Without `overwrite`, `dst` must not exist and the result is generation 1. Bookstore's
reindex (`bookstore/library.py:1042-1153`) keeps calling `create_tree(staging)`, the
import tools and `rename_tree(staging, slug, overwrite=...)` unchanged; its
`_sweep_reserved_trees` (`:291-313`) keeps deleting stale `--staging-` trees and keeps
restoring any `--replaced-` tree left by a pre-upgrade crash.

**Configuration.** Two `PageIndexToolkit` kwargs: `generation_grace_s: int = 3600` and
`lock_timeout_s: float = 30.0`. Bookstore passes its `_STAGING_MAX_AGE_S`
(`library.py:69`) as the grace.

### Component Diagram
```
mutator tool (import_pdf, insert_markdown, add_node, delete_node, update_node,
update_node_content, tag_node, create_tree, rename_tree, …)
        │  async with self._write(tree_name) as txn
        ▼
WriteTransaction (generation.py)            ── deep copy of tree, staged bodies,
        │  publish()                           base signature + generation id
        ├─► tree_lock (locks.py)             ── fcntl, exclusive, cross-process
        ├─► stale check (JSONTreeStore)       ── signature + generation id
        ├─► NodeContentStore.save_body()      ── bodies/<flat_concept_id>.<sha16>.md, atomic
        ├─► project_sidecars (strict)         ── aborts publication on error
        ├─► JSONTreeStore.save()              ── temp + fsync + os.replace (the switch)
        ├─► in-process swap                   ── _trees, _tree_sigs, new HybridPageIndexSearch
        └─► sweep_unreferenced()              ── blobs older than generation_grace_s
readers: _load_tree → immutable dict ──► content loader resolves body_ref ──► blobs
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PageIndexToolkit` (`toolkit.py:54`) | modifies | `_write` transaction replaces `_batch` + `_persist`; all 14 mutating tools ported; `rename_tree`, `delete_tree`, `_search_for` rewritten; two new kwargs |
| `JSONTreeStore` (`store.py:23`) | extends | `fsync` in `save`; `read_generation`; `signature` |
| `NodeContentStore` (`content_store.py:38`) | extends | `bodies/` layout, `save_body`, `load_body`, `load_node`, `sweep_unreferenced`; `loader_for(tree_name, tree)`; legacy fallback |
| `NodeEmbeddingStore` (`embedding_store.py:42`) | modifies | matrix/order paths take a generation id; `invalidate_tree` removes every generation's matrix |
| `HybridPageIndexSearch` (`hybrid_search.py:52`) | modifies | constructed per generation with `generation_id`; `mark_dirty` keyed by tree name |
| `project_sidecars` (`okf/projection.py:97`) | modifies | reads bodies through `load_node`; keeps raising; called strictly from publication |
| `Bookstore` (`bookstore/library.py`) | modifies | passes grace; its own `NodeContentStore` reads through `load_node`; sweep keeps legacy restore |
| `PageIndexLoader` (`pageindex/loader.py:110-227`) | uses | unchanged API; its writes go through the toolkit |
| `PageIndexOrigin` (`parrot_tools/multistoresearch/origins/pageindex.py:70`) | uses | read-only on a `HybridPageIndexSearch` instance; unchanged |
| `OKFToolkit` sidecar readers | uses | sidecars are still `<flat_concept_id>.md` in the tree directory, re-projected on every publish |

### Data Models
```python
# knowledge/pageindex/generation.py (new)
class GenerationInfo(BaseModel):
    """Stored under tree["generation"]; absent on a tree never written by this code."""
    id: int                      # 1 on first publication; +1 per publish
    published_at: str            # ISO-8601 UTC
    parent: Optional[int] = None # previous id, None for the first generation

class BodyRef(BaseModel):
    """Address of an immutable body blob: ``<flat_concept_id>.<sha16>``."""
    flat_concept_id: str
    sha16: str
    @property
    def key(self) -> str: ...
    @classmethod
    def parse(cls, value: str) -> "BodyRef": ...

class PublishReport(BaseModel):
    """Returned by WriteTransaction.publish() and by rename_tree."""
    tree_name: str
    generation: int
    bodies_written: int
    bodies_swept: int
    okf_projected: bool

class StaleGenerationError(RuntimeError): ...
class TreeLockTimeout(TimeoutError): ...
```

Tree JSON additions (both optional for legacy trees):
```json
{"doc_name": "...", "generation": {"id": 7, "published_at": "2026-11-06T15:00:00Z", "parent": 6},
 "structure": [{"node_id": "0001", "concept_id": "...", "body_ref": "intro.3f9a2c1b0e7d4a55", ...}]}
```

### New Public Interfaces
```python
# knowledge/pageindex/locks.py (new)
@asynccontextmanager
async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]:
    """Exclusive cross-process lock on <storage_dir>/.locks/<tree_name>.lock. Raises TreeLockTimeout."""

# knowledge/pageindex/generation.py (new)
class WriteTransaction:
    tree: dict[str, Any]                      # the working copy
    def set_body(self, node: dict[str, Any], markdown: str) -> BodyRef: ...
    def drop_body(self, node: dict[str, Any]) -> None: ...
    async def publish(self) -> PublishReport: ...

# knowledge/pageindex/toolkit.py (modified)
class PageIndexToolkit:
    def __init__(..., generation_grace_s: int = 3600, lock_timeout_s: float = 30.0, **kwargs): ...
    @asynccontextmanager
    async def _write(self, tree_name: str) -> AsyncIterator[WriteTransaction]: ...
    async def vacuum_tree(self, tree_name: str, *, max_age_s: Optional[int] = None) -> dict[str, Any]:
        """Tool: remove unreferenced blobs older than the grace period; returns counts."""
    async def get_generation(self, tree_name: str) -> dict[str, Any]:
        """Tool: the live generation info of a tree (id, published_at, parent)."""
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: tree lock | yes | `fcntl.LOCK_EX \| LOCK_NB` polled every 0.05 s until `timeout`; lock file under `<storage_dir>/.locks/`; raises `TreeLockTimeout`; no-op `True` path removed — a platform without `fcntl` raises `RuntimeError` at first use | — |
| M2: generation primitives | yes | models above; `BodyRef.key = f"{flat}.{sha16}"`; sha16 = `hashlib.sha256(markdown.encode()).hexdigest()[:16]`; `WriteTransaction.publish()` runs the 8 steps in §2 in that order | — |
| M3: content store bodies | yes | layout `<tree>/bodies/<key>.md`; `save_body` = temp + fsync + replace; `load_node` order: `body_ref` → `<flat_concept_id>.md` → `<node_id>.md`; `sweep_unreferenced(tree_name, live_keys, max_age_s)` | — |
| M4: JSON store | yes | `save` adds `os.fsync` on the temp fd before `os.replace`; `read_generation` parses only `generation.id` (full `json.load` is acceptable); `signature` = existing `(st_mtime_ns, st_size)` | — |
| M5: toolkit write path | no | — | 14 mutators with different in-place patterns, join semantics for nested `_write`, `rename_tree` rewrite; needs judgement per method |
| M6: per-generation search | yes | `HybridPageIndexSearch(..., tree_name, generation_id)`; matrix `<tree_name>.g<id>.matrix.npy` / `.node_order.json`; `mark_dirty` uses `tree_name` | — |
| M7: strict projection | yes | `project_sidecars(tree, tree_name, content_store)` reads bodies via `content_store.load_node`; unchanged raise semantics; toolkit calls it from `publish()` step 5 | — |
| M8: Bookstore integration | no | — | touches reindex, sweep and the separate content store; behaviour must be reasoned against 52 existing tests |
| M9: docs page | yes | `wiki/knowledge/pageindex-generation-publication.md` | — |

### Module 1: Tree lock
- **Path**: `knowledge/pageindex/locks.py` (new)
- **Responsibility**: exclusive, cross-process, per-tree lock with a timeout.
- **Depends on**: nothing in this spec. Pattern: `knowledge/wiki/repo_cache.py:50-95`.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/locks.py  (new)
  _LOCK_POLL_SECONDS: float = 0.05           # same cadence as repo_cache.py:23

  class TreeLockTimeout(TimeoutError):
      """Raised when the per-tree lock is not acquired within ``timeout`` seconds."""

  def lock_path(storage_dir: Path, tree_name: str) -> Path:
      """``<storage_dir>/.locks/<tree_name>.lock``; validates the name with the store regex."""  # store.py:20

  @asynccontextmanager
  async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]:
      """Hold ``fcntl.LOCK_EX`` on the lock file; polls with ``asyncio.sleep`` and never blocks the loop.

      Raises:
          TreeLockTimeout: deadline passed.
          RuntimeError: ``fcntl`` is unavailable on this platform.
      """
  ```

### Module 2: Generation primitives
- **Path**: `knowledge/pageindex/generation.py` (new)
- **Responsibility**: `GenerationInfo`, `BodyRef`, `PublishReport`, errors, flattening of
  `concept_id`, and `WriteTransaction` (copy, staged bodies, the 8-step publish).
- **Depends on**: M1, M3, M4, M7.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/generation.py  (new)
  def flatten_concept_id(concept_id: str) -> str:
      """Same flattening add_node uses for OKF sidecar keys."""           # verified: toolkit.py:1172-1189

  def body_sha16(markdown: str) -> str:
      """First 16 hex chars of SHA-256 over the UTF-8 markdown."""

  class WriteTransaction:
      """Copy-on-write unit of work for one tree; created only by PageIndexToolkit._write()."""
      def __init__(self, *, tree_name: str, base_tree: dict[str, Any], base_signature: tuple[int, int] | None,
                   store: JSONTreeStore, content_store: NodeContentStore, storage_dir: Path,
                   lock_timeout_s: float, grace_s: int, projector: Callable[[dict[str, Any], str], bool]) -> None: ...
      tree: dict[str, Any]
      def set_body(self, node: dict[str, Any], markdown: str) -> BodyRef:
          """Stage ``markdown`` for ``node`` (assigns ``concept_id`` when missing) and set ``node['body_ref']``."""
      def drop_body(self, node: dict[str, Any]) -> None:
          """Remove ``body_ref`` from ``node``; the blob is left for the sweep."""
      def live_body_keys(self) -> set[str]:
          """Every ``body_ref`` in ``self.tree``."""
      async def publish(self) -> PublishReport:
          """Steps 1-8 of §2 Overview.

          Raises:
              TreeLockTimeout, StaleGenerationError, ValueError (validation), and whatever
              the strict projector raises; in every case the on-disk tree is unchanged.
          """
  ```

### Module 3: Content store bodies
- **Path**: `knowledge/pageindex/content_store.py` (modifies `:38-240`)
- **Responsibility**: the `bodies/` layout, atomic blob writes, node-aware loading with
  legacy fallback, the sweep, and a tree-aware loader for search.
- **Depends on**: M2 (`BodyRef`).
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/content_store.py  (modifies content_store.py:38)
  class NodeContentStore:
      def bodies_dir(self, tree_name: str) -> Path:                                  # new; next to _tree_dir (:77)
          """``<storage_dir>/<tree_name>/bodies``."""
      def body_path(self, tree_name: str, key: str) -> Path:                          # new
          """``bodies_dir / f"{key}.md"``; validates ``key`` against ``^[A-Za-z0-9_-]+\\.[0-9a-f]{16}$``."""
      def save_body(self, tree_name: str, key: str, markdown: str) -> Path:           # new
          """Atomic write (temp + fsync + os.replace); idempotent when the blob exists."""
      def load_body(self, tree_name: str, key: str) -> Optional[str]:                 # new, cached
      def load_node(self, tree_name: str, node: dict[str, Any]) -> Optional[str]:     # new
          """``body_ref`` → ``<flat_concept_id>.md`` → ``<node_id>.md``; first hit wins."""
      def sweep_unreferenced(self, tree_name: str, tree: dict[str, Any], *, max_age_s: int) -> int:  # new
          """Delete, when older than ``max_age_s``: blobs under ``bodies/`` that no node of ``tree``
          references, and ``<node_id>.md`` files whose node in ``tree`` has a ``body_ref`` and whose
          stem is not that node's flat concept id. Never touches OKF sidecars or non-node files."""
      def load(self, tree_name: str, node_id: str) -> Optional[str]:                  # modifies :118
          """Legacy file first; when absent, resolve ``node_id``/flat concept id through the live tree JSON."""
      def has(self, tree_name: str, node_id: str) -> bool:                            # modifies :135 — same resolution
      def loader_for(self, tree_name: str, tree: Optional[dict[str, Any]] = None) -> Callable[[str], Optional[str]]:  # modifies :212
          """With ``tree``: node_id → node of that tree → ``load_node`` (pinned). Without: ``load`` (live resolution)."""
      def delete_tree(self, tree_name: str) -> int:                                   # modifies :151 — also removes bodies/ and embeddings/
      def save(self, tree_name: str, node_id: str, markdown: str) -> None:            # modifies :111 — atomic write; kept for OKF sidecars
  ```

### Module 4: JSON store
- **Path**: `knowledge/pageindex/store.py` (modifies `:23-111`)
- **Responsibility**: durable save, cheap generation read, signature helper.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/store.py  (modifies store.py:63)
  class JSONTreeStore:
      def save(self, tree_name: str, tree: dict[str, Any]) -> tuple[int, int]:       # modifies :63 — adds os.fsync(fd) before os.replace (:81); returns the new signature
      def signature(self, tree_name: str) -> tuple[int, int] | None:                 # new — moves toolkit._tree_signature (:182-188) here
      def read_generation(self, tree_name: str) -> Optional[int]:                     # new — ``tree["generation"]["id"]`` or None
  ```

### Module 5: Toolkit write path
- **Path**: `knowledge/pageindex/toolkit.py` (modifies `:92-548`, `:765-1261`)
- **Responsibility**: the `_write` transaction and the port of every mutator; per-generation
  search engines; `rename_tree` and `delete_tree` rewrite; the two new tools.
- **Depends on**: M1–M4, M6, M7.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/toolkit.py  (modifies toolkit.py:92)
  class PageIndexToolkit(AbstractToolkit):
      def __init__(self, adapter, storage_dir, reranker=None, lightweight_model=None, model=None,
                   default_bm25_k=20, folder_concurrency=4, content_cache_size=256, embedding_model=None,
                   embedding_dimension=256, embedding_backend=None, use_vec_rank=False, use_embedding_walk=False,
                   generation_grace_s: int = 3600, lock_timeout_s: float = 30.0, **kwargs): ...   # verified: :92-107

      @asynccontextmanager
      async def _write(self, tree_name: str) -> AsyncIterator[WriteTransaction]:        # replaces _batch (:392-400)
          """Open (or join) the transaction for ``tree_name``; publishes on clean exit of the outermost call."""
      def _load_tree(self, tree_name: str) -> dict[str, Any]:                            # modifies :198 — also reloads when generation id changed; result is never mutated
      def _search_for(self, tree_name: str) -> HybridPageIndexSearch:                    # modifies :218 — one engine per (tree, generation)
      async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]:   # modifies :408 — publishes generation 1
      async def delete_tree(self, tree_name: str) -> dict[str, Any]:                     # modifies :430 — under the lock; removes bodies/, embeddings/, lock file, cache entries
      async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:  # modifies :443 — publication of dst from src; no backup tree
      async def get_generation(self, tree_name: str) -> dict[str, Any]: ...              # new tool
      async def vacuum_tree(self, tree_name: str, *, max_age_s: Optional[int] = None) -> dict[str, Any]: ...  # new tool
      # ported unchanged in signature: tag_node :765, insert_markdown :819, insert_ebook :857, insert_content :887,
      # import_file :911, import_pdf :930, import_folder :1004, delete_node :1077, add_node :1110,
      # update_node_content :1198 (now publishes), update_node :1228
  ```
  `_persist` (`:237-252`), `_batch` (`:392-400`), `_batch_depth`/`_batch_dirty` (`:169-170`),
  `_tree_signature`/`_remember_tree_signature` (`:182-196`) and `_save_node_markdown`
  (`:980-1002`) are removed; `_project_okf_sidecars` (`:254-290`) loses its `try/except`
  and becomes the strict projector passed to `WriteTransaction`.

### Module 6: Per-generation search
- **Path**: `knowledge/pageindex/hybrid_search.py` (modifies `:73-135`, `:199-231`),
  `knowledge/pageindex/embedding_store.py` (modifies `:121-127`, `:330-348`)
- **Responsibility**: engines and id-keyed indexes that belong to one generation.
- **Depends on**: M3 (`loader_for(tree_name, tree)`).
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/hybrid_search.py  (modifies hybrid_search.py:73)
  class HybridPageIndexSearch:
      def __init__(self, tree, adapter, reranker=None, model=None, default_bm25_k=20, content_loader=None,
                   embedding_store=None, embed_fn=None, use_vec_rank=False, use_embedding_walk=False,
                   *, tree_name: Optional[str] = None, generation_id: int = 0): ...     # verified: :73-99
      def mark_dirty(self) -> None:                                                      # modifies :119 — invalidates by tree_name, not doc_name (:129)

  # knowledge/pageindex/embedding_store.py  (modifies embedding_store.py:121)
  class NodeEmbeddingStore:
      def _matrix_path(self, tree_name: str, generation_id: int = 0) -> Path:            # modifies :121 — ``<tree_name>.g<id>.matrix.npy``; id 0 keeps the legacy name
      def _order_path(self, tree_name: str, generation_id: int = 0) -> Path:             # modifies :125
      def build_tree_matrix(self, tree_name, nodes, embed_fn, *, generation_id: int = 0): ...   # modifies :204 — atomic writes
      def load_tree_matrix(self, tree_name, *, generation_id: int = 0): ...              # modifies :306
      def invalidate_tree(self, tree_name: str) -> None:                                 # modifies :330 — removes every ``<tree_name>.g*`` matrix/order pair
  ```

### Module 7: Strict projection
- **Path**: `knowledge/pageindex/okf/projection.py` (modifies `:97-156`)
- **Responsibility**: project OKF sidecars from a candidate tree, reading bodies through
  `load_node`, raising on any failure.
- **Depends on**: M3.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/okf/projection.py  (modifies projection.py:97)
  def project_sidecars(tree: dict[str, Any], tree_name: str, content_store: NodeContentStore) -> ProjectionReport:
      """Unchanged signature. Body lookup becomes ``content_store.load_node(tree_name, node)`` (:133-138);
      the old ``<node_id>.md`` removal (:151-154) is dropped — the sweep owns legacy files. Raises on failure."""
  ```

### Module 8: Bookstore integration
- **Path**: `knowledge/bookstore/library.py` (modifies `:69`, `:233-247`, `:291-313`, `:1146`)
- **Responsibility**: pass the grace, read bodies through `load_node`, keep the sweep
  compatible, keep every existing reindex test green.
- **Depends on**: M5, M3.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/library.py  (modifies library.py:233)
  def _toolkit(self, scope: str) -> PageIndexToolkit:
      """Adds ``generation_grace_s=_STAGING_MAX_AGE_S`` to the constructor call at :237-241."""
  async def _sweep_reserved_trees(self, scope: str) -> None:                             # modifies :291
      """Unchanged contract; additionally calls ``toolkit.vacuum_tree`` for each live tree it visits."""
  # every ``self._content_store(scope).load(tree_name, node_id)`` becomes ``load_node(tree_name, node)``
  ```

### Module 9: Documentation
- **Path**: `wiki/knowledge/pageindex-generation-publication.md` (new)
- **Responsibility**: the generation model, the body layout, the lock, the sweep, the
  migration behaviour of legacy trees, and the kwargs.
- **Depends on**: M1–M8.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_tree_lock_excludes_second_process` | M1 | Two `multiprocessing` children; the second raises `TreeLockTimeout` while the first holds the lock |
| `test_tree_lock_releases_on_exception` | M1 | Lock file is free after the context exits with an error |
| `test_body_ref_roundtrip` | M2 | `BodyRef.parse(ref.key) == ref`; sha16 is deterministic |
| `test_publish_increments_generation` | M2 | Generation 1 on first publish, `parent` set afterwards |
| `test_publish_rejects_stale_base` | M2 | External rewrite between load and publish → `StaleGenerationError`, file unchanged |
| `test_publish_failure_leaves_old_generation` | M2 | `os.replace` patched to raise at step 6 → on-disk JSON and cache unchanged |
| `test_publish_projection_failure_aborts` | M2/M7 | Projector raises → no JSON write; staged blobs are orphans |
| `test_save_body_atomic` | M3 | Temp file cleaned on failure; blob never partially visible |
| `test_load_node_fallback_order` | M3 | `body_ref`, then `<flat_concept_id>.md`, then `<node_id>.md` |
| `test_sweep_respects_grace` | M3 | Fresh orphans survive, old ones are removed, live keys never removed |
| `test_store_save_fsyncs` | M4 | `os.fsync` called before `os.replace` |
| `test_write_nested_joins` | M5 | Nested `_write` on one tree publishes once (replaces `test_import_folder_persists_once`) |
| `test_reader_keeps_generation` | M5 | Dict obtained before an edit is unchanged after it; bodies resolve to the old blobs |
| `test_update_node_content_publishes` | M5 | Body update bumps the generation (today it writes no JSON, `toolkit.py:1198-1221`) |
| `test_first_write_migrates_legacy_bodies` | M5 | Legacy tree: first write assigns `body_ref` to every node; legacy files still present until grace |
| `test_rename_tree_no_window` | M5 | A thread polling `store.exists(dst)` every 1 ms during an overwrite rename never sees `False` |
| `test_rename_tree_no_backup_tree` | M5 | No `--replaced-` tree after an overwrite rename (replaces `test_rename_tree_overwrite_replaces_and_removes_backup`, `test_toolkit.py:1251`) |
| `test_rename_tree_refuses_inside_write` | M5 | Replaces `test_rename_tree_refuses_inside_batch` (`:1388`) |
| `test_delete_tree_removes_bodies_and_lock` | M5 | `bodies/`, `embeddings/`, lock file and cache entries gone |
| `test_search_engine_per_generation` | M6 | A new engine after publish; the old instance still answers from the old tree |
| `test_matrix_path_has_generation` | M6 | `invalidate_tree` removes `g1` and `g2` files; `mark_dirty` uses the tree name |
| `test_projection_reads_body_ref` | M7 | Sidecar body comes from the blob, not from `<node_id>.md` |

### Integration Tests
| Test | Description |
|---|---|
| `test_two_processes_one_tree` | Two subprocesses each run `add_node` on the same tree 20 times; final tree has 40 nodes, generation 40, no `StaleGenerationError` escapes (retries on stale) |
| `test_bookstore_reindex_keeps_book_readable` | During `add_book` (updated) a concurrent reader loops `read_section` and never gets a missing tree or an empty body |
| `test_crash_between_bodies_and_json` | Kill after step 4; reopen; tree unchanged; `vacuum_tree` reports the orphans |
| `test_legacy_tree_read_only_untouched` | Opening and searching a pre-upgrade tree writes nothing to disk |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_tree_freshness.py
- packages/ai-parrot/tests/knowledge/pageindex/test_store.py
- packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py
- packages/ai-parrot/tests/knowledge/pageindex/test_tree_ops.py
- packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py
- packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py
- packages/ai-parrot/tests/knowledge/pageindex/test_okf_integration.py
- packages/ai-parrot/tests/knowledge/bookstore/test_library.py
- packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py
- packages/ai-parrot/tests/knowledge/pageindex/test_generation.py
- packages/ai-parrot/tests/knowledge/pageindex/test_locks.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def legacy_tree(tmp_path) -> Path:
    """A tree JSON without ``generation`` plus ``<tree>/<node_id>.md`` sidecars, as written by the current code."""

@pytest.fixture
def enriched_tree(tmp_path) -> Path:
    """A tree whose nodes carry ``concept_id`` and ``type`` so strict OKF projection runs."""

@pytest.fixture
def failing_replace(monkeypatch):
    """Patch ``os.replace`` to raise once on the tree JSON path, leaving blobs written."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Every mutating tool of `PageIndexToolkit` (the 14 listed in §3 M5 plus `create_tree`, `rename_tree`, `delete_tree`) publishes through `_write`; `_persist`, `_batch` and `_save_node_markdown` no longer exist.
- [ ] A tree JSON written by this code carries `generation.id` that increases by exactly 1 per publish.
- [ ] A publish whose base generation is no longer live raises `StaleGenerationError` and writes nothing.
- [ ] Two processes writing one tree serialize on the lock; a lock not acquired within `lock_timeout_s` raises `TreeLockTimeout`.
- [ ] A dict returned by `_load_tree` / `get_tree` is never mutated by a later write; its bodies resolve to the blobs of its generation for at least `generation_grace_s`.
- [ ] Any exception before the JSON switch leaves the on-disk tree and the in-memory cache on the previous generation.
- [ ] A strict OKF projection failure aborts publication.
- [ ] `rename_tree(overwrite=True)` never leaves a moment when `JSONTreeStore.exists(dst)` is `False`, and creates no `--replaced-` tree.
- [ ] Blobs and legacy bodies unreferenced by the live generation are removed only after `generation_grace_s` (default 3600, configurable); Bookstore passes its staging age.
- [ ] Embedding matrix and node-order files are keyed by tree name and generation; `mark_dirty` no longer uses `doc_name`.
- [ ] A pre-upgrade tree opens, searches and reads without any file being written; its first write assigns `body_ref` to every node.
- [ ] All existing Bookstore reindex and sweep tests pass unchanged except the two renamed in §4.
- [ ] `wiki/knowledge/pageindex-generation-publication.md` exists (`parrot sdd techwiki check`).
- [ ] No breaking change to the public signatures of the 19 tools (new optional kwargs only); `__all__` of `knowledge/pageindex/__init__.py` gains `GenerationInfo`, `StaleGenerationError`, `TreeLockTimeout`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified at `dev` @ `8b73aa8c88`. Paths relative to `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from parrot.knowledge.pageindex import (            # knowledge/pageindex/__init__.py:24-43 (__all__, 18 names)
    JSONTreeStore, NodeContentStore, HybridPageIndexSearch, PageIndexToolkit,
    splice_subtree, delete_node, reindex_node_ids,
)
from parrot.knowledge.pageindex.store import JSONTreeStore                     # store.py:23
from parrot.knowledge.pageindex.content_store import NodeContentStore          # content_store.py:38
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore      # embedding_store.py:42 (not in __all__)
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER   # toolkit.py:54, :50 (bookstore/library.py:30 imports both)
from parrot.knowledge.pageindex.tree_ops import delete_node, make_folder_node, splice_subtree, reindex_node_ids  # tree_ops.py:22,35,89,131
from parrot.knowledge.pageindex.okf.projection import project_sidecars, ProjectionReport   # okf/projection.py:97, :33
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id         # okf/concept_id.py:72
from parrot.knowledge.wiki.repo_cache import repo_lock                          # wiki/repo_cache.py:50-53 (pattern only; not imported by M1)
```

### Existing Class Signatures
```python
# knowledge/pageindex/toolkit.py
_MAX_TREES_HARD_CAP = 10                                          # line 49
REPLACED_MARKER = "--replaced-"; _REPLACED_MARKER = REPLACED_MARKER  # lines 50-51
class PageIndexToolkit(AbstractToolkit):                          # line 54
    name = "pageindex"; tool_prefix = "pageindex"                 # lines 89-90
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir, reranker=None, lightweight_model=None,
                 model=None, default_bm25_k=20, folder_concurrency=4, content_cache_size=256,
                 embedding_model=None, embedding_dimension=256, embedding_backend=None,
                 use_vec_rank=False, use_embedding_walk=False, **kwargs)   # lines 92-107
    self._store = JSONTreeStore(storage_dir)                      # line 114
    self._content_store = NodeContentStore(storage_dir, cache_size=content_cache_size)  # line 115
    self._embedding_store: Optional[NodeEmbeddingStore]           # lines 121-134 (only with vec flags)
    self._trees; self._tree_sigs; self._search; self._batch_depth; self._batch_dirty; self._okf_toolkits  # lines 164-172
    def _tree_signature(self, tree_name) -> tuple[int, int] | None   # line 182
    def _remember_tree_signature(self, tree_name) -> None         # line 190
    def _load_tree(self, tree_name) -> dict[str, Any]             # line 198 (cached dict; reload on signature change :203-210)
    def _search_for(self, tree_name) -> HybridPageIndexSearch     # line 218 (engine built with the cached dict :222-233)
    def _persist(self, tree_name) -> None                         # line 237 (save :244, mark_dirty :246-248, projection :252)
    def _project_okf_sidecars(self, tree_name, tree) -> None      # line 254 (enriched rule :279; swallow :289-291)
    async def _run_t3_classification(self, tree, original_id_to_node) -> None  # line 292
    def get_tools(self, permission_context=None, resolver=None) -> list  # line 366
    async def _batch(self, tree_name)                             # line 392 (@asynccontextmanager; user: import_folder :1067)
    async def list_trees(self) -> list[str]                       # line 404
    async def create_tree(self, tree_name, doc_name=None) -> dict # line 408 (direct _store.save :426)
    async def delete_tree(self, tree_name) -> dict                # line 430
    async def rename_tree(self, src, dst, *, overwrite=False) -> dict  # line 443 (flow :465-548)
    async def get_tree(self, tree_name) -> dict                   # line 550 (returns cached dict :552)
    async def search(...)                                         # line 554
    async def retrieve(self, tree_name, query, top_k=5) -> str    # line 621
    async def search_documents_scoped(...)                        # line 658
    async def tag_node(...)                                       # line 765 (in-place :797-808, _persist :811)
    async def insert_markdown(...)                                # line 819 (splice :850, sidecars :851, T3 :853, _persist :854)
    async def insert_ebook(...)                                   # line 857
    async def insert_content(...)                                 # line 887 (delegates :899)
    async def import_file(...)                                    # line 911 (delegates :923)
    async def import_pdf(self, tree_name, pdf_path, parent_node_id=None, with_summaries=True, with_doc_description=False) -> dict  # line 930
    def _save_node_markdown(self, tree_name, original_id_to_node, node_markdown) -> None  # line 980 (save :1002)
    async def import_folder(...)                                  # line 1004 (_batch :1067, semaphore :1024)
    async def delete_node(self, tree_name, node_id) -> dict       # line 1077 (tree_ops :1100, sidecar deletes :1103/:1106)
    async def add_node(...)                                       # line 1110 (splice :1160, flat concept key :1172-1189, save :1190)
    async def update_node_content(...)                            # line 1198 (save :1218, mark_dirty :1221, no JSON write)
    async def update_node(...)                                    # line 1228 (in-place :1255-1258, _persist :1261)
def _capture_node_id_object_map(subtree) -> dict[str, dict]       # line 1331
def _collect_concept_id_keys(...)                                 # line 1381

# knowledge/pageindex/store.py
_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")             # line 20
class JSONTreeStore:                                              # line 23
    def _path_for(self, tree_name) -> Path                        # line 40
    def list_names(self) -> list[str]                             # line 44
    def exists(self, tree_name) -> bool                           # line 54
    def load(self, tree_name) -> dict                             # line 57
    def save(self, tree_name, tree) -> None                       # line 63 (mkstemp :73-77, json.dump :80, os.replace :81; no fsync)
    def delete(self, tree_name) -> bool                           # line 89
    def rename(self, src, dst) -> None                            # line 97 (os.replace :111)

# knowledge/pageindex/content_store.py
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")                # line 35
class NodeContentStore:                                           # line 38
    def __init__(self, storage_dir, cache_size=256)               # line 55
    def _tree_dir(self, tree_name) -> Path                        # line 77
    def _node_path(self, tree_name, node_id) -> Path              # line 81
    def _cache_evict_tree(self, tree_name) -> None                # line 105
    def save(self, tree_name, node_id, markdown) -> None          # line 111 (write_text :115)
    def load(self, tree_name, node_id) -> Optional[str]           # line 118
    def has(self, tree_name, node_id) -> bool                     # line 135
    def delete_node(self, tree_name, node_id) -> bool             # line 141
    def delete_tree(self, tree_name) -> int                       # line 151 (only *.md :160-165)
    def rename_tree(self, src, dst) -> bool                       # line 175 (os.replace :193)
    def list_node_ids(self, tree_name) -> list[str]               # line 198
    def loader_for(self, tree_name) -> Callable[[str], Optional[str]]  # line 211

# knowledge/pageindex/embedding_store.py
class NodeEmbeddingStore:                                         # line 42 (layout docstring :8-17)
    def __init__(self, storage_dir, model_id, dimension, cache_size=512)  # line 75
    @staticmethod
    def content_key(model_id, title, summary) -> str              # line 93
    def _global_dir(self, tree_name) -> Path                      # line 113
    def _matrix_path(self, tree_name) -> Path                     # line 121
    def _order_path(self, tree_name) -> Path                      # line 125
    def build_tree_matrix(self, tree_name, nodes, embed_fn) -> tuple[np.ndarray, list[str]]  # line 204 (np.save :295, write_text :296-298)
    def load_tree_matrix(self, tree_name)                         # line 306
    def invalidate_tree(self, tree_name) -> None                  # line 330

# knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:                                      # line 52
    def __init__(self, tree, adapter, reranker=None, model=None, default_bm25_k=20, content_loader=None,
                 embedding_store=None, embed_fn=None, use_vec_rank=False, use_embedding_walk=False)  # lines 73-99 (self._tree = tree :86)
    def set_content_loader(self, loader) -> None                  # line 101
    def mark_dirty(self) -> None                                  # line 119 (invalidate by doc_name :129)
    def replace_tree(self, tree) -> None                          # line 133 (no callers)
    def _flatten_corpus(self) -> tuple[list[str], list[str]]      # line 145
    def _vec_rank(...)                                            # line 199 (doc_name as tree_name :217-220; build_tree_matrix :229-231)

# knowledge/pageindex/tree_ops.py
def reindex_node_ids(tree) -> None                                # line 22 (only node_id rewritten; concept_id untouched :25-27)
def make_folder_node(...)                                         # line 35
def _assign_okf_concept_ids(target) -> None                       # line 56 (derive_concept_id :78-81; no-op if OKF import fails :71-73)
def splice_subtree(target, subtree, parent_node_id=None) -> list[str]  # line 89 (reindex :126, assign :127)
def delete_node(tree, node_id) -> bool                            # line 131

# knowledge/pageindex/okf/projection.py
class ProjectionReport                                            # line 33
def project_sidecars(tree, tree_name, content_store) -> ProjectionReport  # line 97 (body lookup :133-138, save :145, old node_id removal :151-154; raises)

# knowledge/bookstore/library.py
_STAGING_MARKER = "--staging-"                                    # line 68
_STAGING_MAX_AGE_S = 3600                                         # line 69
def _is_reserved_tree_name(name) -> bool                          # line 72
    def _toolkit(self, scope) -> PageIndexToolkit                 # line 233 (constructor call :237-241)
    def _content_store(self, scope) -> NodeContentStore           # line 244 (separate instance on the same dir)
    def _staging_tree_name(self, slug) -> str                     # line 269
    def _scan_reserved_trees(trees_dir) (staticmethod)            # line 274
    async def _sweep_reserved_trees(self, scope) -> None          # line 291 (restore :301-304, delete :306, stale staging :307-309)
    async def add_book(...)                                       # line 977 (staging :1042, create :1045, rename :1146, cleanup :1147-1153)

# knowledge/wiki/repo_cache.py
_LOCK_POLL_SECONDS = 0.05                                         # line 23
async def repo_lock(lock_path: Path, *, timeout: float, shared: bool = False) -> AsyncIterator[bool]  # line 53 (LOCK_EX|LOCK_NB :77-81, yields acquired :88, no raise on timeout)

# tools/toolkit.py
    llm_dependent_tools: frozenset = frozenset()                  # line 313
    # every public coroutine attribute becomes a tool, prefixed by tool_prefix   # lines 575-618
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `WriteTransaction.publish()` | `JSONTreeStore.save()` | atomic replace, the switch | `store.py:63-81` |
| `WriteTransaction.publish()` | `project_sidecars()` | strict call before the switch | `okf/projection.py:97`, `toolkit.py:288` |
| `WriteTransaction.set_body()` | `derive_concept_id()` | assign missing identity | `tree_ops.py:78-81`, `okf/concept_id.py:72` |
| `PageIndexToolkit._write()` | all mutators | replaces `_persist` / `_batch` | `toolkit.py:237`, `:392`, `:1067` |
| `PageIndexToolkit._search_for()` | `HybridPageIndexSearch(...)` | one engine per generation | `toolkit.py:222-233` |
| `NodeContentStore.loader_for(tree_name, tree)` | `HybridPageIndexSearch.content_loader` | node_id → node → body | `toolkit.py:229`, `hybrid_search.py:101` |
| `tree_lock` | `fcntl` | `LOCK_EX \| LOCK_NB` polled | pattern `wiki/repo_cache.py:77-87` |
| `Bookstore._toolkit()` | `PageIndexToolkit(generation_grace_s=...)` | kwarg | `library.py:237-241` |

### Does NOT Exist (Anti-Hallucination)
- ~~any lock on trees~~ — no `fcntl`, `flock`, `asyncio.Lock` or `repo_lock` use under `knowledge/pageindex/` or in `bookstore/library.py`; the only lock is `NodeEmbeddingStore._cache_lock` (`embedding_store.py:89`, LRU guard)
- ~~`generation`, manifest, version file, `fsync`~~ — none in `store.py`, `content_store.py`, `embedding_store.py`
- ~~a stale-write check in `_persist`~~ — it saves unconditionally (`toolkit.py:244`)
- ~~a copy of the tree before mutation~~ — `_load_tree`, `get_tree`, `_search_for` and every mutator share one dict
- ~~`body_ref`, `bodies/`, `flatten_concept_id`, `WriteTransaction`, `tree_lock`, `vacuum_tree`, `get_generation`~~ — introduced by this spec
- ~~`_get_or_build_okf_toolkit`~~ — mentioned in a comment (`toolkit.py:171`), never defined
- ~~callers of `HybridPageIndexSearch.replace_tree` / `set_content_loader`~~ — none outside `hybrid_search.py`
- ~~an atomic variant of `NodeContentStore.save`~~ — plain `write_text` (`:115`)
- ~~`NodeEmbeddingStore` in `knowledge/pageindex/__init__.__all__`~~ — not exported
- ~~a test exercising `NodeEmbeddingStore` directly~~ — none; `test_toolkit.py:1264` only fakes the directory

### Edit Sites (Blueprint Anchors)

Verified against: `8b73aa8c88`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `knowledge/pageindex/locks.py` | CREATE | — | — | — |
| `knowledge/pageindex/generation.py` | CREATE | — | — | — |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    def _tree_signature(self, tree_name: str) -> tuple[int, int] \| None:` | `toolkit.py:182` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    def _load_tree(self, tree_name: str) -> dict[str, Any]:` | `toolkit.py:198` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    def _search_for(self, tree_name: str) -> HybridPageIndexSearch:` | `toolkit.py:218` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    def _persist(self, tree_name: str) -> None:` | `toolkit.py:237` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    def _project_okf_sidecars(self, tree_name: str, tree: dict[str, Any]) -> None:` | `toolkit.py:254` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    async def _batch(self, tree_name: str):` | `toolkit.py:393` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    async def rename_tree(` | `toolkit.py:443` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `    def _save_node_markdown(` | `toolkit.py:980` | 1 |
| `knowledge/pageindex/toolkit.py` | MODIFY | `        async with self._batch(tree_name):` | `toolkit.py:1067` | 1 |
| `knowledge/pageindex/store.py` | MODIFY | `    def save(self, tree_name: str, tree: dict[str, Any]) -> None:` | `store.py:63` | 1 |
| `knowledge/pageindex/content_store.py` | MODIFY | `    def save(self, tree_name: str, node_id: str, markdown: str) -> None:` | `content_store.py:111` | 1 |
| `knowledge/pageindex/content_store.py` | MODIFY | `    def delete_tree(self, tree_name: str) -> int:` | `content_store.py:151` | 1 |
| `knowledge/pageindex/content_store.py` | MODIFY | `    def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]:` | `content_store.py:212` | 1 |
| `knowledge/pageindex/embedding_store.py` | MODIFY | `    def _matrix_path(self, tree_name: str) -> Path:` | `embedding_store.py:121` | 1 |
| `knowledge/pageindex/embedding_store.py` | MODIFY | `    def invalidate_tree(self, tree_name: str) -> None:` | `embedding_store.py:330` | 1 |
| `knowledge/pageindex/hybrid_search.py` | MODIFY | `    def mark_dirty(self) -> None:` | `hybrid_search.py:119` | 1 |
| `knowledge/pageindex/okf/projection.py` | MODIFY | `def project_sidecars(` | `okf/projection.py:97` | 1 |
| `knowledge/bookstore/library.py` | MODIFY | `_STAGING_MAX_AGE_S = 3600` | `library.py:69` | 1 |
| `knowledge/bookstore/library.py` | MODIFY | `    async def _sweep_reserved_trees(self, scope: str) -> None:` | `library.py:291` | 1 |
| `knowledge/pageindex/__init__.py` | MODIFY | `__all__ = [` | `__init__.py:24` | 1 |
| `wiki/knowledge/pageindex-generation-publication.md` (repo root) | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Atomic file writes: `tempfile.mkstemp(dir=same_dir)` → write → `os.fsync(fd)` → `os.replace`,
  as `JSONTreeStore.save` does (`store.py:73-81`) plus the `fsync`. Same for blobs.
- Lock polling with `asyncio.sleep` and `LOCK_NB` (`wiki/repo_cache.py:77-87`); never a
  blocking `flock` on the event loop.
- Blob writes and `fsync` run in `asyncio.to_thread` when publishing more than a few
  bodies (an import writes hundreds).
- Pydantic v2 models for `GenerationInfo`, `BodyRef`, `PublishReport`; `self.logger`
  throughout.
- Keep the tool surface stable: new tools (`get_generation`, `vacuum_tree`) are public
  coroutines like the rest (`tools/toolkit.py:575-618`).
- Retry policy on `StaleGenerationError` belongs to the caller: the toolkit's tools re-run
  their mutator at most twice on a fresh copy before raising. Document this on each tool.

### Known Risks / Gotchas
- **First write of a legacy tree is a full pass.** Every node gets a `body_ref` and a blob
  on the first publish; for a 5,000-node book that is 5,000 small atomic writes. Acceptable
  once per tree; the publish runs blob writes in a thread.
- **OKF sidecars are written in place.** A reader of `<flat_concept_id>.md` during a publish
  may see the new projection while holding the old tree. Accepted: sidecars are a derived,
  idempotent projection; versioning them is out of scope.
- **`mark_dirty` by `doc_name`** (`hybrid_search.py:129`) invalidates the wrong tree
  when `doc_name != tree_name` — fixed by M6, and `test_toolkit.py:1264` relies on the old
  file names.
- **`import_folder` concurrency.** Concurrent `insert_content` calls join one transaction
  and splice into the same working copy between awaits, as today they splice into the
  cached dict. The transaction is single-process and asyncio-serialized; this is unchanged.
- **Lock file litter.** `.locks/` holds one file per tree; `delete_tree` removes it under
  the lock; a stale lock file is harmless (`fcntl` locks die with the process).
- **Network filesystems.** `fcntl` on NFS may be advisory or absent; `tree_lock` raises
  `RuntimeError` when `fcntl` is unavailable rather than pretending.
- **Existing tests change.** `test_rename_tree_overwrite_replaces_and_removes_backup`
  (`test_toolkit.py:1251`), `test_rename_tree_refuses_inside_batch` (`:1388`),
  `test_batch_keeps_cached_tree` (`test_tree_freshness.py:50`) and
  `test_import_folder_persists_once` (`test_folder_import.py:101`) encode the old mechanism
  and are replaced by the tests in §4, not deleted silently.
- **Bookstore's separate `NodeContentStore`** (`library.py:244-247`) reads bodies by
  `node_id` (`:374`); it moves to `load_node` so a reindex never serves another node's body.
- **Eleven other body readers** (listed in §2 "Readers that key bodies by `node_id`") rely on
  the live-JSON resolution in `load`/`has`/`loader_for`. A deliberate consequence: they read
  the live generation, as today, not a pinned one. Changing them is out of scope.
- **`concept_id` collisions.** `derive_concept_id(title, parent_path)` is deterministic, so two
  siblings with the same title share a flat id. Blob keys still differ by content hash, and
  identical bodies share one immutable blob, which is harmless. The live-JSON resolution must map
  `node_id` first and fall back to the flat id only when the node id is unknown.
- **Sweep and the grace period.** A reader that holds a generation longer than
  `generation_grace_s` can lose its blobs; one hour matches the staging sweep and the
  longest request this code serves. The grace is configurable for operators who need more.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| none | — | `fcntl`, `hashlib`, `tempfile`, `os` are stdlib; `pydantic` v2 already a dependency |

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-generation-publication
entries:
  - id: every-write-publishes-a-generation
    statement: Every mutation of a PageIndex tree must be published as a complete generation through one atomic replace of the tree JSON, never by mutating the cached tree in place.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py"]
    contradicts: []
    supersedes: []
    rationale: Readers must keep one consistent generation for a whole request and a writer must never overwrite another process's edit.
    rejected_alternatives: ["Generation manifest file", "Keep _batch and add a lock only"]
  - id: bodies-are-immutable-blobs-by-identity
    statement: Node bodies must be stored as immutable blobs addressed by flattened concept_id plus content hash and referenced from the node, never overwritten in place.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py"]
    contradicts: []
    supersedes: []
    rationale: A stable address makes a generation one JSON replace and keeps old generations readable during the grace period.
    rejected_alternatives: ["Copy <node_id>.md per generation", "Hard-link bodies per generation"]
  - id: strict-okf-projection-on-publish
    statement: OKF sidecar projection for a candidate generation must run before the JSON switch and its failure must abort publication.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py"]
    contradicts: []
    supersedes: []
    rationale: A published tree with stale sidecars is a silent corruption; failing the write is cheaper than finding it later.
    rejected_alternatives: ["Best-effort projection after the switch (current behaviour)"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:5d1f9e6def03e11e3cafa5368473a2878618a3f39a81e4414e0c068690798570 evaluation_digest=sha256:af04202ec87ca620a4ff90974b1105ddc23171c43e5a820f19f826db79b8a1f0 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: copy-on-write, generations, tree-optimizer
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "copy-on-write",
      "generations",
      "tree-optimizer"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:af04202ec87ca620a4ff90974b1105ddc23171c43e5a820f19f826db79b8a1f0",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:5d1f9e6def03e11e3cafa5368473a2878618a3f39a81e4414e0c068690798570",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:080e80f14e256c449ca5d1b6b7cbe838aad0c0bdcdc0f8ece372a4b8e2d9c9c8",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Which spec owns generation publication, the writer lock and reader pinning — *Resolved in brainstorm*: this spec (`pageindex-generation-publication`), first of six.
- [x] Do edit operations also publish a generation, or only optimize — *Resolved in brainstorm*: every write publishes a generation.
- [x] Generations as a new manifest, or as an extension of the existing swap — *Resolved in brainstorm*: extend the staging tree plus `rename_tree` swap.
- [x] Body storage once every edit publishes a generation — *Resolved in brainstorm*: the stable address (identity-keyed bodies).
- [x] Retention of old generations — *Resolved in brainstorm*: configurable, one hour by default.
- [x] Old document revisions after a re-import — *Resolved in brainstorm*: only the latest; the previous one is kept for the grace period (applies to `pageindex-segment-store`; the sweep here is designed to host it).
- [x] Lock pattern — *Resolved in brainstorm*: `knowledge/wiki/repo_cache.py::repo_lock` is the existing `fcntl` pattern.
- [ ] Should `StaleGenerationError` retries inside the tools be configurable (today: at most two re-runs)? — *Owner: Jesus Lara* (can be decided during implementation)
- [ ] `vacuum_tree` as an exposed tool, or internal plus a CLI command only? — *Owner: Jesus Lara* (can be decided during implementation)

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (exploration doc
> `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` has `**Status**: exploration`,
> not `accepted`) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/knowledge/pageindex-generation-publication.md` — create: the generation model,
    body blobs by identity, the cross-process lock, the sweep and grace period, legacy-tree
    migration on first write, the two toolkit kwargs and the two new tools.
  - `wiki/knowledge/pageindex.md` — update: link the new page from the storage layout section.
- **API modules**:
  - `parrot.knowledge.pageindex.generation`
  - `parrot.knowledge.pageindex.locks`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-06 | Jesus Lara (with Claude) | Initial draft from brainstorm revision 4 |
| 0.2 | 2026-11-07 | Jesus Lara (with Claude) | Found at `/sdd-task`: eleven more body readers keyed by `node_id`. `load`/`has`/`loader_for(tree_name)` resolve through the live tree JSON so those callers stay untouched; `sweep_unreferenced` takes the tree and never removes OKF sidecars or non-node files. |
