---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [bookstore, pageindex, ingest, reindex, atomicity]
---

# Feature Specification: Bookstore re-index via staging tree + atomic PageIndex rename

**Feature ID**: FEAT-615
**Date**: 2026-09-30
**Author**: Jesus Lara (spec drafted by Claude)
**Status**: approved
**Target version**: next minor
**Source**: ledger `issue:759176f0cf1a` (tech_debt/minor, discovered from `spec:bookstore-reindex-identity`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`Bookstore.add_book` re-indexes an already-catalogued book **destructively
before it knows the new ingest will succeed**. On the `"updated"` path it runs
`toolkit.delete_tree(slug)` and `self._invalidate_graph(slug)` *first*, then
`create_tree` + the format-specific ingest (`import_pdf` / `insert_markdown` /
`insert_content` / `insert_ebook`). If the ingest fails (LLM error, bad PDF,
missing loader, …) the error handler deletes the half-built tree, and the
library is left with:

- the **old catalog row** still pointing at `tree_name=<slug>` — a tree that
  no longer exists (`get_toc` / `read_section` / `search_book` break);
- **all relations, judgements and the community partition already gone**,
  even though the book's content never changed.

Ledger issue text (verbatim):

> library.py add_book: on 'updated', delete_tree + _invalidate_graph run
> before create_tree/ingest. If ingest fails, the old catalog row points at a
> missing tree and relations are already gone. Pre-existing tree-delete
> ordering, made slightly worse by invalidation. Suggested: ingest under a
> temp tree name, or invalidate only after ingest succeeds. Also minor:
> disambiguate_title passes an empty LLM-drafted title through (strip + stem
> fallback); CLI update cannot clear authors/topics.

The `/sdd-fix` fast lane declined it: *"a safe swap needs a temp tree + rename
that PageIndexToolkit does not offer"*. Doing it right needs a new, general
PageIndex capability (rename/replace a tree, including its sidecar directory,
embedding matrix and OKF sidecar frontmatter) plus a staging workflow in the
bookstore — hence a feature, not a hotfix.

### Goals
- G1: A failed re-index leaves the previous book **fully intact**: old tree
  JSON, sidecars, catalog row, relations, judgements and communities.
- G2: A successful re-index replaces the tree under the **same `book_id` /
  `tree_name`** (identity guarantee from `bookstore-reindex-identity` holds),
  and only then invalidates the graph.
- G3: `PageIndexToolkit` gains a general `rename_tree(src, dst, *, overwrite=False)`
  that moves a tree (JSON + content dir + embedding matrix) and keeps every
  in-memory cache and OKF sidecar consistent; it is **not** an LLM tool.
- G4: Leftovers from a crashed process (staging / replaced trees) are
  recovered or swept on the next ingest, never surfacing as books.
- G5: `disambiguate_title` never returns an empty title.
- G6: `bookstore update` CLI can clear authors and topics.

### Non-Goals (explicitly out of scope)
- Cross-process atomicity guarantees for concurrent readers (an MCP server
  reading while a CLI re-indexes may observe a sub-second window where the
  tree JSON is absent). Documented in §7, not solved.
- Locking between two concurrent `bookstore add` processes on the same book.
- Changing the `"added"` path's identity rules, slug generation, or carding.
- Making `delete_tree` also remove the `embeddings/` subdirectory (a separate,
  pre-existing gap noted in §7).

---

## 2. Architectural Design

### Overview

**Staging-then-swap.** Every `add_book` ingest (both `"added"` and
`"updated"`) builds the tree under a reserved staging name
`<slug>--staging-<8 hex>`; carding reads the staging tree. Only after ingest
and carding succeed does the bookstore call
`toolkit.rename_tree(staging, slug, overwrite=(status == "updated"))`, then
`_invalidate_graph(slug)` (updated path only), then `catalog.upsert(card)`.
On any failure before the rename, only the staging tree is deleted — the
live tree, card and graph are untouched.

`--` is a reserved marker: `slugify` collapses every non-alphanumeric run to a
single `-`, so no real `book_id` can contain `--`. Staging names
(`--staging-`) and swap backups (`--replaced-`) are therefore unambiguous and
never collide with catalogued books. Max length: 64 (slug cap) + 10 + 8 = 82,
inside the tree-store limit of 128.

**`PageIndexToolkit.rename_tree`** (general PageIndex capability):

1. Validate both names (store regex), `src != dst`, `src` exists, neither tree
   is inside an open `_batch`. If `dst` exists and `overwrite=False` →
   `ValueError`.
2. If `dst` exists (overwrite): move `dst` → `<dst>--replaced-<8 hex>`
   (JSON first, then content dir — the tree "disappears" before its content).
3. Move `src` → `dst` (content dir first, then JSON — the tree "appears" only
   once its content is in place). The embedding per-tree matrix/order files
   are named after the tree, so they are invalidated for `src` **before** the
   dir move (the global content-addressed tier moves with the dir and is
   reused on rebuild).
4. On failure in step 3: move the backup back to `dst`, re-raise.
5. Delete the backup tree (best-effort, logged).
6. Drop `_trees` / `_search` entries for `src`, `dst` and the backup; evict the
   content-store LRU for all three; drop `_okf_toolkits[src]`; reload `dst`
   and, if OKF-enriched, re-project its sidecars (their frontmatter embeds the
   tree name in the resource URI).

File moves use `os.replace` inside the same `storage_dir` (same filesystem,
atomic per path). The JSON store and content store each get a small `rename`
primitive; the toolkit orchestrates.

**Crash recovery (bookstore).** At the start of `add_book`, the bookstore
sweeps the target scope's trees dir:
- `<slug>--replaced-<hex>` where `<slug>` tree is **missing** → restore it via
  `rename_tree(replaced, slug)` (crash between swap steps 2 and 3).
- `<slug>--replaced-<hex>` where `<slug>` exists → delete it (crash after 3).
- `<slug>--staging-<hex>` older than 1 hour (JSON mtime) → delete it. Younger
  ones are left alone (may belong to a concurrent process).

`_all_taken_slugs` ignores reserved names (they are not book ids).

**Minor items.** `disambiguate_title` strips its input and falls back to the
de-slugified stem when empty. The `update` CLI gains `--clear-authors` /
`--clear-topics` (pass `[]` to `update_card`, which already accepts empty lists).

### Component Diagram
```
Bookstore.add_book
  ├─ _sweep_reserved_trees(scope)            (M3, crash recovery)
  ├─ staging = _staging_tree_name(slug)       (M3)
  ├─ toolkit.create_tree(staging) + ingest    (existing tools, staging name)
  │     └─ on error → toolkit.delete_tree(staging); raise   (live book untouched)
  ├─ get_tree(staging) → derive_toc → _draft_card(tree_name=staging)
  ├─ toolkit.rename_tree(staging, slug, overwrite=updated)   (M2)
  │     ├─ JSONTreeStore.rename / NodeContentStore.rename   (M1)
  │     └─ NodeEmbeddingStore.invalidate_tree + OKF re-projection
  ├─ _invalidate_graph(slug)                  (updated only, AFTER success)
  ├─ drop Bookstore._content_stores[scope]    (stale LRU of the old tree)
  └─ catalog.upsert(card)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `JSONTreeStore` | extends | new `rename(src, dst)` (no overwrite; toolkit orchestrates) |
| `NodeContentStore` | extends | new `rename_tree(src, dst)` + cache eviction |
| `NodeEmbeddingStore.invalidate_tree` | uses | called for `src` before the dir move |
| `PageIndexToolkit` | extends | new `rename_tree`; `exclude_tools = ("rename_tree",)` |
| `okf.projection.project_sidecars` | uses (via `_project_okf_sidecars`) | re-project after rename |
| `Bookstore.add_book` | modifies | staging-then-swap ordering |
| `Bookstore._all_taken_slugs` | modifies | ignore reserved names |
| `carding.disambiguate_title` | modifies | strip + stem fallback |
| `cli.update_cmd` | modifies | `--clear-authors` / `--clear-topics` |

### Data Models
No new Pydantic models. `BookCard.tree_name` keeps equal to `book_id`.

### New Public Interfaces
```python
class PageIndexToolkit:
    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]: ...
class JSONTreeStore:
    def rename(self, src: str, dst: str) -> None: ...
class NodeContentStore:
    def rename_tree(self, src: str, dst: str) -> bool: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: store rename primitives | yes | signatures below; `os.replace`; `FileExistsError` if dst present; `FileNotFoundError` if src JSON absent | — |
| M2: `PageIndexToolkit.rename_tree` | yes | 6-step algorithm in §2; return dict shape below; `exclude_tools` | — |
| M3: Bookstore staging-then-swap + sweep | no | — | ordering across ingest/carding/graph/catalog and recovery rules need care; keep on the thinking model |
| M4: `disambiguate_title` empty-title fallback | yes | `title = title.strip() or _stem_to_title(stem) or stem or "Untitled"` at function entry | — |
| M5: CLI `--clear-authors` / `--clear-topics` | yes | flags below; mutually exclusive with `--author`/`--topic` → `ClickException` | — |

### Module 1: Store rename primitives
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py`, `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py`
- **Responsibility**: Move one tree's JSON file / sidecar directory to a new name atomically per path.
- **Depends on**: existing stores
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/pageindex/store.py (after delete(), line 91)
  class JSONTreeStore:  # verified: store.py:23
      def rename(self, src: str, dst: str) -> None:
          """Atomically move ``<src>.json`` to ``<dst>.json`` via ``os.replace``.

          Raises:
              ValueError: invalid name (``_validate_name``).
              FileNotFoundError: ``src`` does not exist.
              FileExistsError: ``dst`` already exists (callers must clear it first).
          """

  # modifies packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py (after delete_tree(), line 158)
  class NodeContentStore:  # verified: content_store.py:37
      def rename_tree(self, src: str, dst: str) -> bool:
          """Move the ``<src>/`` sidecar directory (incl. ``embeddings/``) to ``<dst>/``.

          Evicts LRU entries of both names. Returns ``False`` when ``src`` has no
          directory (nothing to move), ``True`` otherwise.

          Raises:
              ValueError: invalid name.
              FileExistsError: ``<dst>/`` already exists.
          """
  ```

### Module 2: `PageIndexToolkit.rename_tree`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`
- **Responsibility**: Orchestrate a (optionally overwriting) tree rename with rollback and full cache/OKF/embedding consistency. Programmatic API only.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
  class PageIndexToolkit(AbstractToolkit):  # verified: toolkit.py:50
      name = "pageindex"            # verified: toolkit.py:85
      tool_prefix = "pageindex"     # verified: toolkit.py:86
      exclude_tools = ("rename_tree",)  # NEW — AbstractToolkit.exclude_tools verified: parrot/tools/toolkit.py:240

      async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:
          """Rename tree ``src`` to ``dst`` (JSON, sidecar dir, embeddings) — not an LLM tool.

          With ``overwrite=True`` an existing ``dst`` is first moved to a
          ``<dst>--replaced-<hex>`` backup, restored if the move of ``src``
          fails, and deleted after success.

          Returns:
              ``{"src": src, "dst": dst, "replaced": bool}``.

          Raises:
              KeyError: ``src`` does not exist.
              ValueError: invalid names, ``src == dst``, ``dst`` exists without
                  ``overwrite``, or either tree is inside an open ``_batch``.
          """
  ```

### Module 3: Bookstore staging-then-swap + crash sweep
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
- **Responsibility**: Reorder `add_book` so nothing live is destroyed before ingest + carding succeed; reserved-name helpers; sweep/restore leftovers; ignore reserved names in `_all_taken_slugs`; drop the scope's stale `NodeContentStore` after a swap.
- **Depends on**: Module 2
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
  _STAGING_MARKER = "--staging-"    # NEW module constant
  _REPLACED_MARKER = "--replaced-"  # NEW — must equal the marker PageIndexToolkit.rename_tree uses
  _STAGING_MAX_AGE_S = 3600         # NEW

  def _is_reserved_tree_name(name: str) -> bool:
      """True for staging/replaced tree names (contain ``--``, which ``slugify`` never emits)."""

  class Bookstore:  # add_book verified: library.py:923
      def _staging_tree_name(self, slug: str) -> str:
          """Return ``f"{slug}--staging-{secrets.token_hex(4)}"``."""

      async def _sweep_reserved_trees(self, scope: str) -> None:
          """Restore orphaned ``--replaced-`` backups whose live tree is missing,
          delete those whose live tree exists, and delete ``--staging-`` trees
          whose JSON mtime is older than ``_STAGING_MAX_AGE_S``. Best-effort:
          logs and never raises."""
  ```
  `add_book` new order (updated and added paths unified):
  sweep → compute `slug` (existing rules) → `staging = _staging_tree_name(slug)`
  → `create_tree(staging, doc_name=…)` → ingest with `tree_name=staging`
  (on error: `delete_tree(staging)`, re-raise) → `get_tree(staging)` →
  `derive_toc` → `_draft_card(tree_name=staging, …)` → title/card build
  (unchanged, `tree_name=slug` on the card) → `rename_tree(staging, slug,
  overwrite=status == "updated")` (on error: `delete_tree(staging)`, re-raise)
  → if updated: `_invalidate_graph(slug)` → `self._content_stores.pop(scope, None)`
  → `catalog.upsert(card)` → optional `relate_books`.

### Module 4: `disambiguate_title` empty-title fallback
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py`
- **Responsibility**: Never return an empty/whitespace title.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # modifies carding.py:94 (signature unchanged)
  def disambiguate_title(title: str, taken: set[str], *, toc_entries: list[TocEntry], stem: str) -> str:
      """… An empty/whitespace ``title`` is replaced by ``_stem_to_title(stem)``
      (then ``stem``, then ``"Untitled"``) before the collision check."""
  ```

### Module 5: CLI `update --clear-authors / --clear-topics`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py`
- **Responsibility**: Let the CLI clear list fields.
- **Depends on**: none (`Bookstore.update_card` already accepts `[]`)
- **Interface Skeleton**:
  ```python
  # modifies cli.py:373-402
  @click.option("--clear-authors", is_flag=True, help="Remove all authors.")
  @click.option("--clear-topics", is_flag=True, help="Remove all topics.")
  def update_cmd(book_id, title, authors, topics, summary, clear_authors: bool, clear_topics: bool) -> None:
      """… ``--clear-authors`` with ``--author`` (or ``--clear-topics`` with
      ``--topic``) is a usage error; a clear flag alone counts as "something to do"."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_json_store_rename_moves_file` | M1 | `<src>.json` gone, `<dst>.json` loads identical dict |
| `test_json_store_rename_refuses_existing_dst` | M1 | `FileExistsError`, both files untouched |
| `test_content_store_rename_tree_moves_dir_and_evicts_cache` | M1 | sidecars readable under dst; cached src entries evicted |
| `test_content_store_rename_tree_missing_src_dir_returns_false` | M1 | no dir → `False` |
| `test_rename_tree_basic` | M2 | tree, sidecars, `get_tree`/`search` served under dst; src gone |
| `test_rename_tree_refuses_existing_dst_without_overwrite` | M2 | `ValueError` |
| `test_rename_tree_overwrite_replaces_and_removes_backup` | M2 | dst has src content; no `--replaced-` leftovers |
| `test_rename_tree_overwrite_rolls_back_on_failure` | M2 | monkeypatch 2nd move to raise → original dst restored, exception propagates |
| `test_rename_tree_invalidates_search_engine_cache` | M2 | pre-built `_search[dst]` does not serve old content |
| `test_rename_tree_reprojects_okf_sidecars` | M2 | OKF-enriched tree: sidecar frontmatter URI names dst |
| `test_rename_tree_not_exposed_as_tool` | M2 | `"rename_tree"` absent from `list_tool_names()` |
| `test_rename_tree_refuses_inside_batch` | M2 | `ValueError` inside `_batch(src)` |
| `test_reindex_failed_ingest_keeps_old_book` | M3 | re-index with ingest forced to fail → old tree/toc/section readable, card unchanged, relations+judgements+communities intact |
| `test_reindex_success_swaps_tree_same_book_id` | M3 | new content under same `book_id`; graph invalidated; no reserved trees left |
| `test_add_failed_ingest_leaves_no_tree` | M3 | first-time add failure → no slug tree, no staging tree, no card |
| `test_sweep_restores_orphaned_replaced_tree` | M3 | only `<slug>--replaced-x` present → restored as `<slug>` |
| `test_sweep_deletes_stale_staging_keeps_fresh` | M3 | old-mtime staging deleted, fresh one kept |
| `test_all_taken_slugs_ignores_reserved_names` | M3 | staging names not in the taken set |
| `test_disambiguate_title_empty_falls_back_to_stem` | M4 | `""`/`"  "` → de-slugified stem |
| `test_cli_update_clear_authors_topics` | M5 | lists emptied; conflict with `--author` → usage error |

Existing tests that must stay green: `tests/knowledge/bookstore/test_library.py`
(incl. `test_reindex_invalidates_relations_and_communities`,
`test_reindex_preserves_manual_card_edits`), `tests/knowledge/bookstore/test_cli.py`,
`tests/knowledge/pageindex/test_toolkit.py`, `test_store.py`, `test_content_store.py`,
`test_okf_projection.py`.

### Integration Tests
| Test | Description |
|---|---|
| `test_reindex_roundtrip_markdown` (bookstore/test_library.py) | add → modify file → add (updated) → `get_toc`, `read_section`, `search_book` reflect new content, same `book_id` |

### Test Data / Fixtures
Reuse `store` / `book_md` fixtures from `tests/knowledge/bookstore/conftest.py`
(no LLM; markdown ingest). Force ingest failure by monkeypatching
`PageIndexToolkit.insert_markdown` to raise.

---

## 5. Acceptance Criteria

- [ ] A re-index whose ingest raises leaves the prior tree JSON, sidecars, card,
      relations, judgements and communities byte-/row-identical (M3 test).
- [ ] A successful re-index keeps `book_id == tree_name == slug` and invalidates
      the graph only after the swap.
- [ ] No `--staging-` / `--replaced-` tree remains after any successful or
      failed `add_book` in the same process.
- [ ] `PageIndexToolkit.rename_tree` exists, is excluded from generated tools,
      and restores `dst` when the swap fails.
- [ ] OKF sidecars of a renamed enriched tree reference the new tree name.
- [ ] `disambiguate_title` never returns an empty string.
- [ ] `bookstore update <id> --clear-authors --clear-topics` empties both lists.
- [ ] `ruff check` clean on touched files; all listed test files pass with
      `PYTHONPATH=packages/ai-parrot/src`.
- [ ] Ledger `issue:759176f0cf1a` closed `--resolved-by spec:FEAT-615` at `/sdd-done`.

---

## 6. Codebase Contract

> Verified against `4cda67d27` (origin/dev, 2026-09-30).

### Verified Imports
```python
from parrot.knowledge.pageindex.content_store import NodeContentStore  # verified: bookstore/library.py:27
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit          # verified: bookstore/library.py:28
from parrot.knowledge.pageindex.utils import structure_to_list           # verified: pageindex/toolkit.py (lazy import in _project_okf_sidecars)
from parrot.knowledge.pageindex.okf.projection import project_sidecars   # verified: okf/projection.py (used at toolkit.py _project_okf_sidecars)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/store.py
_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")          # line 20
class JSONTreeStore:                                              # line 23
    def __init__(self, storage_dir: str | Path): ...              # line 31  (self._dir)
    @staticmethod
    def _validate_name(tree_name: str) -> None: ...               # line 36
    def _path_for(self, tree_name: str) -> Path: ...              # line 42
    def list_names(self) -> list[str]: ...                        # line 46
    def exists(self, tree_name: str) -> bool: ...                 # line 56
    def load(self, tree_name: str) -> dict[str, Any]: ...         # line 59
    def save(self, tree_name: str, tree: dict[str, Any]) -> None: # line 65 (tempfile + os.replace)
    def delete(self, tree_name: str) -> bool: ...                 # line 91

# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
class NodeContentStore:                                           # line 37
    def __init__(self, storage_dir: str | Path, cache_size: int = 256) -> None:  # line 54
    def _tree_dir(self, tree_name: str) -> Path: ...              # line 82  (self._dir / tree_name)
    def _cache_evict_tree(self, tree_name: str) -> None: ...      # line 110
    def delete_tree(self, tree_name: str) -> int: ...             # line 158 (rmdir fails silently if embeddings/ present)
    def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]: ...  # line 197

# packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py
class NodeEmbeddingStore:                                         # line 42
    def _matrix_path(self, tree_name) -> Path  # <storage>/<tree>/embeddings/<tree>.matrix.npy   line 121
    def _order_path(self, tree_name) -> Path   # <storage>/<tree>/embeddings/<tree>.node_order.json line 125
    def invalidate_tree(self, tree_name: str) -> None: ...        # line 330

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                          # line 50
    name = "pageindex"; tool_prefix = "pageindex"                 # lines 85-86
    self._store: JSONTreeStore                                    # __init__
    self._content_store: NodeContentStore                         # __init__
    self._embedding_store: Optional[NodeEmbeddingStore]           # __init__ (None unless vec_rank/embedding_walk)
    self._trees: dict[str, dict[str, Any]]                        # __init__
    self._search: dict[str, HybridPageIndexSearch]                # __init__
    self._batch_depth: dict[str, int]                             # __init__
    self._okf_toolkits: dict[str, Any]                            # line 167
    def _load_tree(self, tree_name: str) -> dict[str, Any]: ...   # line 177 (KeyError if absent)
    def _persist(self, tree_name: str) -> None: ...               # line 205
    def _project_okf_sidecars(self, tree_name: str, tree: dict[str, Any]) -> None: ...  # line 221 (best-effort)
    async def _batch(self, tree_name: str): ...                   # line 362 (asynccontextmanager)
    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]: ...  # line 377
    async def delete_tree(self, tree_name: str) -> dict[str, Any]: ...  # line 398
    async def get_tree(self, tree_name: str) -> dict[str, Any]: ...     # line 410

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()                           # line 240 (honoured in _generate_tools, line 570)

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py
def project_sidecar(node: dict, tree_name: str, body: str) -> str: ...  # line 50 — tree_name goes into the resource URI

# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class Bookstore:
    self._content_stores: dict[str, NodeContentStore]             # line 202 (own LRU, separate from the toolkit's)
    def _toolkit(self, scope: str) -> PageIndexToolkit: ...        # line 223
    def _content_store(self, scope: str) -> NodeContentStore: ...  # line 234
    def _all_taken_slugs(self) -> set[str]: ...                   # line 242
    async def add_book(self, file_path, scope="project", title=None, authors=None,
                       topics=None, force=False, *, relate=False) -> tuple[BookCard, str]: ...  # line 923
    async def _draft_card(self, path, tree_name, scope, ...) -> ...  # line 1105 (reads sidecars via loader_for(tree_name))
    def _invalidate_graph(self, book_id: str) -> None: ...        # line 1275
    def update_card(self, book_id, *, title=None, authors=None, topics=None, summary=None) -> BookCard  # line 1356 ([] accepted)

# packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py
def slugify(text: str) -> str: ...            # line 49 — collapses non-alnum runs to a single "-", cap 64 (never emits "--")
def unique_slug(base: str, taken: set[str]) -> str: ...  # line 73
def _stem_to_title(stem: str) -> str: ...     # before line 94
def disambiguate_title(title: str, taken: set[str], *, toc_entries: list[TocEntry], stem: str) -> str: ...  # line 94
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PageIndexToolkit.rename_tree` | `JSONTreeStore.rename`, `NodeContentStore.rename_tree` | method call | M1 (new) |
| `PageIndexToolkit.rename_tree` | `NodeEmbeddingStore.invalidate_tree` | method call when `_embedding_store` not None | `embedding_store.py:330` |
| `PageIndexToolkit.rename_tree` | `_project_okf_sidecars(dst, tree)` | method call | `toolkit.py:221` |
| `Bookstore.add_book` | `PageIndexToolkit.rename_tree` | await | M2 (new) |
| `Bookstore.add_book` | `_invalidate_graph` | moved after swap | `library.py:1275` |

### Does NOT Exist (Anti-Hallucination)
- ~~`PageIndexToolkit.rename_tree` / `move_tree` / `replace_tree` / `copy_tree`~~ — none exist today (this spec adds `rename_tree` only)
- ~~`JSONTreeStore.rename`~~, ~~`NodeContentStore.rename_tree`~~ — added by M1
- ~~`NodeContentStore.evict_tree` (public)~~ — only private `_cache_evict_tree`
- ~~`NodeEmbeddingStore.rename_tree`~~ — do not add; invalidate + rebuild instead
- ~~`Bookstore.reindex_book`~~ — re-index is `add_book` with an existing path/sha
- ~~`PageIndexToolkit.exclude_tools`~~ — not set today (inherits `()`); M2 sets it
- ~~a lock/`fcntl` layer in bookstore~~ — none; concurrency is out of scope

### Edit Sites (Blueprint Anchors)

Verified against: `4cda67d27`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` | MODIFY | `    def delete(self, tree_name: str) -> bool:` | `store.py:91` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` | MODIFY | `    def delete_tree(self, tree_name: str) -> int:` | `content_store.py:158` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    tool_prefix = "pageindex"` | `toolkit.py:86` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def get_tree(self, tree_name: str) -> dict[str, Any]:` (insert `rename_tree` before it, after `delete_tree`) | `toolkit.py:410` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `                taken \|= {p.stem for p in loc.trees_dir.glob("*.json")}` | `library.py:256` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `        if status == "updated":` (block 982-989 through `await toolkit.create_tree(slug, doc_name=title or path.stem)`) | `library.py:982` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `        tree = await toolkit.get_tree(slug)` | `library.py:1043` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `        catalog.upsert(card)` | `library.py:1100` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `            tree_name=slug,` — ingest calls at 1000/1008/1019/1025/1032 and `_draft_card` at 1047 become `staging`; **1087 (BookCard) stays `slug`** | `library.py:1000..1087` | 7 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` | MODIFY | `    if title.casefold() not in taken:` | `carding.py:102` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@click.option("--summary", default=None, help="New summary.")` / `    if title is None and not authors and not topics and summary is None:` | `cli.py:378` / `cli.py:389` | 1 / 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_store.py` | MODIFY | append tests | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py` | MODIFY | append tests | — | — |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | append tests | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | append tests | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | append tests | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Atomic per-path moves with `os.replace` inside one `storage_dir` (same
  filesystem), mirroring `JSONTreeStore.save`.
- Order of moves: when a tree is taken **out** of a name, JSON first then
  content dir; when a tree is put **into** a name, content dir first then JSON.
- Blocking filesystem work in async methods is small metadata ops (renames);
  keep them inline like `delete_tree` does today — no `to_thread` needed.
- `self.logger` / module `logger`; Google docstrings; no new dependencies.
- The `--replaced-` marker string is shared by M2 and M3: define it once as a
  module constant in `pageindex/toolkit.py` (`_REPLACED_MARKER`) and import it
  in `library.py` rather than duplicating the literal.

### Known Risks / Gotchas
- **Cross-process readers**: between the two moves of a swap a concurrent
  reader may see no tree for ~ms. Accepted (non-goal); the previous code had a
  far larger window (the whole ingest).
- **Bookstore's own `NodeContentStore` LRU** (`library.py:202`) is separate
  from the toolkit's and would serve the old tree's sections after a swap —
  M3 drops `self._content_stores[scope]` after the rename.
- **OKF sidecars embed the tree name** (`project_sidecar`): after a rename
  they must be re-projected under `dst`, or resource URIs point at the staging
  name. Carding reads sidecars through the staging name, which is correct.
- **Embedding matrix files are named after the tree**: invalidate `src` before
  moving the dir; the global tier travels with the dir.
- **`delete_tree` leaves `embeddings/`** (its `rmdir` fails silently on a
  non-empty dir). Pre-existing; `NodeContentStore.rename_tree` must move the
  whole directory (not just `*.md`) so nothing stays behind under the staging
  name. Not fixed for `delete_tree` here.
- **Sweep vs. a concurrent process**: only `--staging-` trees older than 1 h
  are swept; `--replaced-` trees are only restored when the live tree is
  missing, otherwise deleted.
- `_draft_card` must receive `tree_name=staging`; the `BookCard` must carry
  `tree_name=slug`. Mixing them up is the most likely implementation bug.

### External Dependencies
None.

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-615-bookstore-reindex-atomic-swap`)
  off `origin/dev`; the `sdd-coder` engine gives each task a sub-worktree.
- **Module dependency graph**:
  - M2 → M1 (calls `JSONTreeStore.rename`, `NodeContentStore.rename_tree`).
  - M3 → M2 (calls `PageIndexToolkit.rename_tree`, imports `_REPLACED_MARKER`).
  - M4, M5: no edges — run concurrently with M1.
- **Shared files**: none across modules (M1 = store.py + content_store.py;
  M2 = pageindex/toolkit.py; M3 = library.py; M4 = carding.py; M5 = cli.py).
  Test files likewise split per module.
- **Exclusive resources**: none (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**: none. `bookstore-reindex-identity` (hotfix)
  is already merged to `dev` (`236f148cb` → `71f3938a6`).

---

## 8. Open Questions

- [ ] Staging sweep age threshold: 1 h hard-coded constant, or configurable via
      bookstore config? Default in this spec: constant `_STAGING_MAX_AGE_S = 3600`. — *Owner: Jesus Lara*: 1h hard constant
- [x] Should `rename_tree` ever be exposed as an LLM tool (e.g. non-overwriting
      only)? This spec excludes it. — *Owner: Jesus Lara*: yes, included
- [x] Hotfix or feature? — *Resolved by user*: feature — touches
      `PageIndexToolkit` (new rename capability) and requires a temporary tree.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — source is ledger `issue:759176f0cf1a`, no brainstorm/proposal/intake)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-30 | Claude (for Jesus Lara) | Initial draft from ledger issue:759176f0cf1a |
