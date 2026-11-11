# TASK-5477: Notebook lifecycle, annotated `read_section`/`get_toc`, manual edges survive re-index

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5475
**Assigned-to**: unassigned

---

## Context

Implements the first half of spec **Module 4** (§3), goals G2/G4, design-research S1/S2/S10/S11.
A notebook is a PageIndex tree in the scope's `trees/` dir: `<book_id>_notes` (per book) or `_library_notes`
(per scope). Registration is **lazy**: Bookstore upserts the `kind="notes"` row the first time it sees the
conventional tree on disk; the MCP facade never writes `library.db`. Annotated reads surface notebook nodes
anchored to a book node. `remap_anchors`, `doctor --notes` and the `add_book` hook are TASK-5479.

---

## Scope

- Add module constants `LIBRARY_NOTEBOOK = "_library_notes"`, `NOTEBOOK_SUFFIX = "_notes"` and helper
  `notebook_tree_name(book_id: Optional[str]) -> str`.
- `Bookstore.notebook_for(book_id)` / `library_notebook(scope)` — catalog row, or lazy upsert of a `kind="notes"`
  card when the conventional tree exists on disk (sync; `JSONTreeStore(loc.trees_dir).exists`).
- `async Bookstore.ensure_notebook(book_id, scope="project")` — `create_tree` on the scope toolkit when missing, then register.
- `async Bookstore.annotations_for(book_id, node_id)` and a sync helper `_annotations_sync(card, scope, node_id)`
  used by `read_section`; per-notebook index cached by the tree file signature `(st_mtime_ns, st_size)`.
- `read_section` gains `annotations: list[dict]`; `get_toc` entries gain `has_notes: bool`. **Keep both sync**
  (planner decision for spec §8 Q1): read the notebook through `JSONTreeStore.load` + `NodeContentStore.load_current`.
- `resolve_book` refuses `kind="notes"` rows (a notebook is not a book).
- `_invalidate_graph` deletes only `deterministic`, `llm`, `community` origins (S10).
- `remove_book(book_id, *, with_notes=False)`: default keeps the notebook (row kept, `notes_for` cleared);
  `with_notes=True` also deletes the notebook tree and row.
- Tests in `test_library.py` and `test_reindex_hardening.py`.

**NOT in scope**: `remap_anchors`, `doctor(notes=)`, `add_book` hook (TASK-5479); `find_books` (TASK-5480);
the facade (TASK-5478).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Notebook lifecycle, annotations, annotated reads, relation-origin filter, remove_book(with_notes) |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | Lifecycle + annotated read tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` | MODIFY | Manual edges survive re-index |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already imported in library.py (verified: library.py:25-48)
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER
from .catalog import CatalogStore, merged_cards, merged_communities, merged_relations, merged_search
from .config import LibraryLocation
from .models import REL_WEIGHTS, BookCard, BookCommunity, BookRelation, CardDraft, RelateSummary
# ADD
from parrot.knowledge.pageindex.store import JSONTreeStore          # verified: pageindex/store.py:23
from parrot.knowledge.pageindex.utils import structure_to_list      # verified: pageindex/utils.py:298
from .models import Anchor, Annotation                               # created by TASK-5475
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
_STAGING_MARKER = "--staging-"                                      # line 73
def _is_reserved_tree_name(name: str) -> bool                        # line 158
class BookstoreError(...)                                            # line 197
class Bookstore:                                                     # line 264
    def has_llm(self) -> bool                                        # line 313 (property)
    def _location(self, scope) -> LibraryLocation                    # line 320
    def _catalog(self, scope) -> CatalogStore                        # line 326
    def _toolkit(self, scope) -> PageIndexToolkit                    # line 331
    async def _ready_toolkit(self, scope) -> PageIndexToolkit        # line 343
    async def _book_operation_lock(self, scope, tree_name)           # line 365 (async context manager)
    def _content_store(self, scope) -> NodeContentStore              # line 387
    def _stores(self) -> list[tuple[str, CatalogStore]]              # line 392
    def resolve_book(self, book_id) -> tuple[BookCard, LibraryLocation]   # line 621 (catalog.get per scope)
    def get_toc(self, book_id) -> dict                               # line 638 — keys book_id,title,toc_digest,entries
    def read_section(self, book_id, node_id) -> dict                 # line 664 — body via _content_store(scope).load_current
    def _invalidate_graph(self, book_id) -> None                     # line 1960 — store.delete_relations(book_id=book_id) at :1969
    async def remove_book(self, book_id: str) -> bool                # line 1973
# packages/ai-parrot/src/parrot/knowledge/pageindex/store.py
class JSONTreeStore: __init__(storage_dir) mkdirs; _path_for(name) -> Path (:40); exists(name) (:54); load(name) -> dict, FileNotFoundError (:57)
# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py: NodeContentStore.load_current(tree_name, node_id) -> Optional[str]   # line 271
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py: create_tree(tree_name, doc_name=None) (:745); node metadata lives at node["metadata"] (tag_node :1958)
# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py (after TASK-5475): list_cards(kind="book"), notebook_for(book_id), library_notebook(), upsert(card), remove(book_id), get(book_id) (:374), delete_relations(book_id=None, origin=None) (:526)
```

### Does NOT Exist
- ~~`Bookstore.notebook_for` / `library_notebook` / `ensure_notebook` / `annotations_for`~~ — added here.
- ~~`Bookstore.remap_anchors`~~ — TASK-5479, do not add here.
- ~~`PageIndexToolkit.load_tree` (public sync)~~ — the toolkit's loader is private `_load_tree`; use `JSONTreeStore` instead.
- ~~`TreeNode`~~ — node model is `PageIndexNode`; trees are plain dicts here.
- ~~`delete_relations(origins=[...])`~~ — takes a single `origin`; loop over the three computed origins.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.read_section",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.get_toc",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.resolve_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._invalidate_graph",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.remove_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore"
  ]
}
```

---

## Implementation Notes

- **Lazy card fields** (spec §2): `book_id = tree_name = "<id>_notes"` (or `_library_notes`), `title = "Notes — <book title>"`
  (or `"Library notebook (<scope>)"`), `source_format="tree"`, `source_path=str(JSONTreeStore._path_for(name))`,
  `source_sha256=""` until TASK-5482 defines the snapshot hash (write an empty string — the column is NOT NULL),
  `card_origin="fallback"`, `added_at` = UTC ISO now, `kind="notes"`, `notes_for=<book_id>` or `None`.
- **Identity is `(scope, book_id)`** (S11): a book notebook lives in the **book's** scope; `annotations_for`
  resolves the book first, then looks for the notebook in `loc.scope` only. Anchors whose `scope` differs from the
  book's scope are ignored.
- **Annotation shape**: walk `structure_to_list(tree["structure"])`; a node is an annotation of `(book_id, node_id)`
  when any `Anchor.model_validate(a)` in `node["metadata"]["anchors"]` matches both. Skip malformed anchors (log
  at debug; `doctor --notes` reports them in TASK-5479). `anchor_status` comes from `metadata.get("anchor_status",
  "current")`. Body = `NodeContentStore.load_current(note_tree, node_id) or ""`.
- **Cache**: `self._annotation_cache: dict[tuple[str, str], tuple[tuple[int, int], dict[str, list[Annotation]]]]`
  keyed `(scope, note_tree)` → (file signature, index by anchored node_id). Initialise in `__init__`.
- `get_toc.has_notes`: one index lookup per entry — never one tree read per entry.
- Never raise from the annotation path into `read_section`: a corrupt notebook yields `[]` + a warning.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add imports, constants and `notebook_tree_name` — *why*: one naming rule for every caller (facade, CLI, import).
2. `notebook_for` / `library_notebook` / `ensure_notebook` — *why*: lazy registration (G2, S2).
3. `_notebook_index` + `annotations_for` + annotated `read_section`/`get_toc` — *why*: G4 reads, sync contract kept.
4. `resolve_book` refuses notes; `_invalidate_graph` origin filter; `remove_book(with_notes)` — *why*: S1/S10.
5. Tests; `ruff check --fix`.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# AFTER `_STAGING_MARKER = "--staging-"` (verified: library.py:73, 1 occurrence)
#: Per-scope library notebook tree (Dewey-like sectors) and the per-book notebook suffix (FEAT-876).
LIBRARY_NOTEBOOK = "_library_notes"
NOTEBOOK_SUFFIX = "_notes"


def notebook_tree_name(book_id: Optional[str]) -> str:
    """Tree name of a book's notebook, or of the scope's library notebook when ``book_id`` is ``None``."""
    return LIBRARY_NOTEBOOK if book_id is None else f"{book_id}{NOTEBOOK_SUFFIX}"
```
```python
# INSIDE class Bookstore — new section placed after `read_section` (verified: library.py:664, 1 occurrence)
    # ------------------------------------------------------------------
    # Notebooks (FEAT-876)
    # ------------------------------------------------------------------
    def notebook_for(self, book_id: str) -> Optional[BookCard]:
        """Registered or on-disk ``<book_id>_notes`` in the book's scope (lazy ``kind='notes'`` upsert)."""
        card, loc = self.resolve_book(book_id)
        return self._registered_notebook(loc.scope, notebook_tree_name(card.book_id), card)

    def library_notebook(self, scope: str) -> Optional[BookCard]:
        """Registered or on-disk ``_library_notes`` of ``scope``."""
        return self._registered_notebook(scope, LIBRARY_NOTEBOOK, None)

    def _registered_notebook(self, scope: str, tree_name: str, book: Optional[BookCard]) -> Optional[BookCard]:
        catalog = self._catalog(scope)
        existing = catalog.get(tree_name)
        if existing is not None and existing.kind == "notes":
            return existing.model_copy(update={"scope": scope})
        trees = JSONTreeStore(self._location(scope).trees_dir)
        if not trees.exists(tree_name):
            return None
        # FILL IN: build the kind="notes" BookCard per Implementation Notes "Lazy card fields"; catalog.upsert(card);
        #   log info "registered notebook %r (%s)"; return it with scope stamped — bounded by AC-1
        raise NotImplementedError

    async def ensure_notebook(self, book_id: Optional[str], scope: str = "project") -> BookCard:
        """Create the conventional notebook tree when missing and register it."""
        if book_id is not None:
            card, loc = self.resolve_book(book_id)
            scope = loc.scope
        # FILL IN: toolkit = await self._ready_toolkit(scope); if the tree does not exist,
        #   await toolkit.create_tree(name); then return the _registered_notebook(...) result — bounded by AC-1
        raise NotImplementedError

    def _notebook_index(self, scope: str, tree_name: str) -> dict[str, list[Annotation]]:
        """``{node_id_or_book_key: [Annotation]}`` for one notebook, cached by tree file signature."""
        # FILL IN: stat JSONTreeStore._path_for(tree_name); missing → {}; signature hit → cached index;
        #   else load, walk structure_to_list, validate anchors, build index keyed f"{book_id}#{node_id}" — bounded by Notes
        raise NotImplementedError

    async def annotations_for(self, book_id: str, node_id: str) -> list[Annotation]:
        """Notes anchored to ``(book_id, node_id)``; ``[]`` when the book has no notebook."""
        card, loc = self.resolve_book(book_id)
        return self._annotations_sync(card, loc.scope, node_id)

    def _annotations_sync(self, card: BookCard, scope: str, node_id: str) -> list[Annotation]:
        try:
            index = self._notebook_index(scope, notebook_tree_name(card.book_id))
        except Exception as exc:  # noqa: BLE001 — a broken notebook must never break a book read
            logger.warning("notebook for %r unreadable: %s", card.book_id, exc)
            return []
        return list(index.get(f"{card.book_id}#{node_id}", []))
```
**Why**: `read_section` stays sync (spec §8 Q1, owner implementer → decided here), so the notebook is read with the
synchronous `JSONTreeStore`/`NodeContentStore` pair; the async `annotations_for` is a thin wrapper for the API.

```python
# read_section (verified: library.py:664) — add one key to the returned dict
            "annotations": [note.model_dump() for note in self._annotations_sync(card, loc.scope, node_id)],
# get_toc (verified: library.py:638) — needs the scope: change `card, _ = self.resolve_book(book_id)` to `card, loc = ...`
#   FILL IN: entries = [{**entry.model_dump(), "has_notes": bool(index.get(f"{card.book_id}#{entry.node_id}"))} ...]
#   using ONE _notebook_index call (guarded like _annotations_sync) — bounded by AC-3
# resolve_book (verified: library.py:621) — skip rows whose kind == "notes" (continue to the next scope / raise)
# _invalidate_graph (verified: library.py:1960, line :1969) — REPLACE `store.delete_relations(book_id=book_id)` with:
            for origin in ("deterministic", "llm", "community"):
                store.delete_relations(book_id=book_id, origin=origin)
# remove_book (verified: library.py:1973) — signature `async def remove_book(self, book_id: str, *, with_notes: bool = False) -> bool:`
#   FILL IN: inside the existing lock, after catalog.remove(book_id): look up catalog.notebook_for(book_id);
#   with_notes → await toolkit.delete_tree(<id>_notes) (ignore missing) + catalog.remove(<id>_notes);
#   else → catalog.upsert(notebook.model_copy(update={"notes_for": None})) (orphan notes) — bounded by AC-5
```

### FILL IN checklist
- [ ] `_registered_notebook` lazy card — bounded by AC-1 and Notes
- [ ] `ensure_notebook` — bounded by AC-1
- [ ] `_notebook_index` cache + anchor walk — bounded by AC-2, S11
- [ ] `get_toc.has_notes` — bounded by AC-3
- [ ] `resolve_book` notes refusal — bounded by AC-4
- [ ] `remove_book(with_notes)` — bounded by AC-5
- [ ] Test bodies — bounded by spec §4 M4 rows

---

## Acceptance Criteria

- [ ] AC-1: a `<book>_notes` tree created directly with the scope toolkit's `create_tree` is registered once by `notebook_for` (exactly one `kind="notes"` row; `list_books()` unchanged).
- [ ] AC-2: a node tagged with `metadata={"anchors": [{"book_id": b, "node_id": n}]}` appears in `read_section(b, n)["annotations"]`; other nodes return `[]`; a same-id book in the other scope never sees it (S11).
- [ ] AC-3: `get_toc` entries carry `has_notes`; existing keys unchanged.
- [ ] AC-4: `resolve_book("<id>_notes")` raises `BookstoreError`; `list_books`/`catalog_search` never return notes rows.
- [ ] AC-5: `remove_book(b)` keeps the notebook (row with `notes_for=None`, tree intact); `remove_book(b, with_notes=True)` removes both.
- [ ] AC-6: `_invalidate_graph` after an `"updated"` re-index leaves `origin="manual"` rows in place (S10).
- [ ] Existing `test_library.py` / `test_reindex_hardening.py` tests still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py -q`

---

## Test Specification

```python
# test_library.py — fixtures `store`, `book_md`, `locations` are defined IN test_library.py (lines 34-56), not conftest.py
async def test_notebook_lazy_registration(store, book_md): ...
async def test_read_section_carries_annotations(store, book_md): ...   # add_book → ensure_notebook → add_node + tag_node(anchors)
async def test_get_toc_has_notes(store, book_md): ...
async def test_annotations_resolve_by_scope_and_id(tmp_path, fake_adapter): ...  # project + global LibraryLocation with same book id
async def test_remove_book_keeps_notebook_by_default(store, book_md): ...
def test_resolve_book_refuses_notebook(store): ...
# test_reindex_hardening.py
async def test_reindex_keeps_manual_relations(...): ...   # upsert_relations([BookRelation(origin="manual")]) → re-add changed book → row still there
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug bookstore-notebooks-shared-pageindex --feature-id FEAT-876`).
   Run tests with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
2. **Read the spec** at the path above (§2 Overview, the module section named in Context, §6, §7).
3. **Check dependencies** — every `Depends-on` task must be `done` in
   `sdd/tasks/index/bookstore-notebooks-shared-pageindex.json`.
4. **Verify the Codebase Contract** before writing code; if an entry is stale, fix the contract here first.
   Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `in-progress` (set `started_at`) and commit only that file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Validate**: `ruff check --fix <files>` and the Validation Commands below.
8. **Commit the code** — stage only the files listed in this task.
9. **Close** with `parrot sdd task close TASK-5477 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
