# TASK-5480: Two-step `find_books` over sectors and manual relation sheets

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5479
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 5** (§3), goals G5/G7, decision `sectors-are-the-authoritative-which-books-answer`.
Dewey-like sectors in each scope's `_library_notes` are the authoritative answer to "which books treat X";
`find_books` searches them first and falls back to the catalog FTS. Relation sheets (notebook nodes anchoring
≥ 2 books) become `origin="manual"` graph edges.

---

## Scope

- `async Bookstore.find_books(query, top_k=5)` (library.py): search each scope's `_library_notes` with
  `PageIndexToolkit.search(use_bm25=True, use_llm_walk=self.has_llm)`, merge project-first, resolve each sector's
  anchors against the catalog, and return `{source: "sectors", sectors: [{code, title, books: [{book_id, title,
  scope, entries: [{node_id, title, start_page, end_page}]}]}]}`. No sector tree or no hit → `{source:
  "catalog_fts", books: [card.brief()...], hint: "..."}`. Without `bm25s`, degrade to a title-substring match over
  sector nodes and say so in `hint`. Never reads a book body.
- `BookstoreToolkit.find_books(query, top_k=5)` + add `"find_books"` to `read_tools` (14 → 15).
- `mcp_server.py` description: the funnel names `bookstore_find_books` first.
- Create `knowledge/bookstore/notebooks.py` with `async relation_sheets(store, scope=None) -> list[BookRelation]`:
  every notebook node anchoring ≥ 2 distinct books → `BookRelation(origin="manual", rel=metadata.get("rel") or
  "parallels", weight=1.0, rationale=<node body, truncated>, computed_at=now)`; for directed kinds
  (`influenced_by`, `responds_to`) the first anchor is `src`; symmetric kinds emit one edge per pair.
  Also `async apply_relation_sheets(store, scope=None) -> int` that upserts them into the owning store.
- Tests: `test_library.py`, `test_toolkit.py`, `test_mcp_server.py` (tool count 15), `test_relations.py`, new `test_notebooks.py`.

**NOT in scope**: drafting (TASK-5481); CLI `relate --from-notes` (TASK-5483).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `find_books` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` | MODIFY | `find_books` tool + `read_tools` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` | MODIFY | Funnel description |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/notebooks.py` | CREATE | `relation_sheets`, `apply_relation_sheets` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | `find_books` tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` | MODIFY | Tool registered + payload |
| `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py` | MODIFY | Tool count 15, description |
| `packages/ai-parrot/tests/knowledge/bookstore/test_relations.py` | MODIFY | Manual edges survive `relate_books` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_notebooks.py` | CREATE | `relation_sheets` tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, LIBRARY_NOTEBOOK, notebook_tree_name   # TASK-5477
from parrot.knowledge.bookstore.models import Anchor, BookRelation, RelationKind     # models.py:39, :210; Anchor from TASK-5475
from parrot.knowledge.pageindex.store import JSONTreeStore                            # pageindex/store.py:23
from parrot.knowledge.pageindex.utils import structure_to_list                        # pageindex/utils.py:298
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
def catalog_search(self, query, top_k=8) -> list[BookCard]       # line 617 (merged_search)
def _stores(self) -> list[tuple[str, CatalogStore]]               # line 392
def _relations_store_for(self, book_id) -> CatalogStore           # line 1027 — the store that owns an edge's src
async def _ready_toolkit(self, scope) -> PageIndexToolkit         # line 343
def library_notebook(self, scope) -> Optional[BookCard]           # TASK-5477
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
async def search(self, tree_name, query, top_k=20, use_bm25=True, use_llm_walk=..., ...)   # line 1743 (llm_walk only when adapter is not None, :1768)
# packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                          # line 30
    read_tools: frozenset[str] = frozenset({...14 names})         # line 39
    async def catalog_search(self, query: str, top_k: int = 8) -> list[dict]   # line 62 — docstring pattern + clamp 1-50
# packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py
    description = (                                               # line 93 — 1 occurrence
# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py: SYMMETRIC_RELS (see BookRelation docstring :210) — directed kinds influenced_by / responds_to
# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py: upsert_relations(relations) (:496) — after TASK-5475 never overwrites a manual row with a computed one
# packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py:58  assert len(server.tools) == 14   → becomes 15
```

### Does NOT Exist
- ~~`Bookstore.find_books`, `BookstoreToolkit.find_books`~~ — added here.
- ~~`parrot.knowledge.bookstore.notebooks`~~ — created here (TASK-5481 adds drafting to it).
- ~~communities inside `find_books`~~ — out by design (they stay behind `communities` / `related_books`).
- ~~a `bm25s` hard dependency~~ — optional; degrade as specified.

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
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/notebooks.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_relations.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_notebooks.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py#BookstoreToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py#create_bookstore_mcp_server",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.upsert_relations",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.search"
  ]
}
```

---

## Implementation Notes

- A sector node is a `_library_notes` node with `metadata.sector_code`; the sector's books come from anchors
  without `node_id` and its entries from anchors with `node_id` (look the entry up in the book card's `toc`).
- Resolve anchors through `(scope, book_id)` (S11): skip an anchor whose book is not catalogued in that scope.
- `BookstoreToolkit.find_books` docstring is the LLM-facing description — say it is the first step
  ("Which books of the library treat X, and where — librarian's sectors first, catalog search as fallback").
- `relation_sheets` must canonicalise nothing itself — `CatalogStore.upsert_relations` does that.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. `notebooks.py` with `relation_sheets` / `apply_relation_sheets` — *why*: G7, no dependency on find_books.
2. `Bookstore.find_books` — *why*: G5 two-step retrieval.
3. Toolkit tool + `read_tools`; MCP description — *why*: agents start the funnel there.
4. Tests (update the tool count assertion).

### `packages/ai-parrot/src/parrot/knowledge/bookstore/notebooks.py` (CREATE)
```python
"""Bookstore notebooks: relation sheets (and, from TASK-5481, drafting) — FEAT-876."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.utils import structure_to_list

from .library import Bookstore, LIBRARY_NOTEBOOK, NOTEBOOK_SUFFIX
from .models import Anchor, BookRelation

logger = logging.getLogger(__name__)

_DIRECTED = frozenset({"influenced_by", "responds_to"})


async def relation_sheets(store: Bookstore, scope: Optional[str] = None) -> list[BookRelation]:
    """Every notebook node anchoring two or more books, as ``origin='manual'`` relations."""
    now = datetime.now(timezone.utc).isoformat()
    relations: list[BookRelation] = []
    for location in store.locations:
        if scope is not None and location.scope != scope:
            continue
        trees = JSONTreeStore(location.trees_dir)
        for name in trees.list_names():
            if name != LIBRARY_NOTEBOOK and not name.endswith(NOTEBOOK_SUFFIX):
                continue
            # FILL IN: load tree; for each node with >= 2 distinct anchored book_ids build relations:
            #   rel = metadata.get("rel") or "parallels"; directed → (first, other) pairs; symmetric → every pair;
            #   rationale = body (NodeContentStore via store._content_store(location.scope).load_current) truncated to 500
            #   chars; skip invalid rel values with a warning — bounded by AC-4
    return relations


async def apply_relation_sheets(store: Bookstore, scope: Optional[str] = None) -> int:
    """Upsert the sheet relations into the store owning each edge's source; returns the edge count."""
    relations = await relation_sheets(store, scope)
    # FILL IN: group by store._relations_store_for(rel.src_book_id) and upsert_relations per store
    return len(relations)
```

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# INSIDE class Bookstore, Notebooks section (TASK-5477)
    async def find_books(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """Which books treat ``query`` and where: sectors of every ``_library_notes`` first, catalog FTS fallback."""
        sectors: list[dict[str, Any]] = []
        degraded: Optional[str] = None
        for location in self.locations:
            if self.library_notebook(location.scope) is None:
                continue
            toolkit = await self._ready_toolkit(location.scope)
            # FILL IN: hits = await toolkit.search(LIBRARY_NOTEBOOK, query, top_k=top_k, use_bm25=True,
            #   use_llm_walk=self.has_llm); on ImportError (no bm25s) → title substring match + degraded hint;
            #   map hits to sector dicts via node metadata (sector_code, anchors) — bounded by AC-1, AC-2
        if sectors:
            return {"source": "sectors", "sectors": sectors[:top_k], **({"hint": degraded} if degraded else {})}
        return {
            "source": "catalog_fts",
            "books": [card.brief() for card in self.catalog_search(query, top_k=top_k)],
            "hint": "No librarian sector matched; draft one with `bookstore notebook draft --library`.",
        }
```

### `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` (MODIFY)
```python
# read_tools (verified: toolkit.py:39, 1 occurrence) — add "find_books" to the frozenset
# NEW method next to catalog_search (verified: toolkit.py:62)
    async def find_books(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """Which books of the library treat a topic, and where — START HERE.

        Answers from the librarian's sectors (the library notebook) with direct pointers to the
        table-of-contents entries; falls back to catalog search when no sector matches.

        Args:
            query: Topic or keywords (e.g. "stoic ethics").
            top_k: Maximum sectors or books returned (clamped to 1-50).
        """
        # FILL IN: clamp top_k like catalog_search; return await self._bookstore.find_books(query, top_k)
```

### `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` (MODIFY)
```python
# description = ( (verified: mcp_server.py:93, 1 occurrence) — replace the funnel sentence:
        "Research funnel: bookstore_find_books (which books treat X, and where) → "
        "bookstore_agentic_retrieve (validated citations), with bookstore_get_toc → "
        "bookstore_search_book → bookstore_read_section for targeted reading; "
        "bookstore_catalog_search is the lexical fallback."
```

### FILL IN checklist
- [ ] `relation_sheets` node walk — bounded by AC-4
- [ ] `apply_relation_sheets` grouping — bounded by AC-4
- [ ] `find_books` hit → sector mapping and bm25 degradation — bounded by AC-1, AC-2
- [ ] `BookstoreToolkit.find_books` clamp + delegate
- [ ] Tests incl. tool-count update — bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: with a sector anchoring a book and a ToC entry, `find_books` returns `source="sectors"` with that entry; without `_library_notes` it returns `source="catalog_fts"` + `hint`.
- [ ] AC-2: both scopes' `_library_notes` are consulted, project first; `find_books` never reads a book body.
- [ ] AC-3: `BookstoreToolkit.read_tools` grows by exactly `find_books`; `create_bookstore_mcp_server` serves 15 tools and names `bookstore_find_books` first.
- [ ] AC-4: `apply_relation_sheets` writes `origin="manual"` edges (default `parallels`, directed kinds keep the first anchor as `src`) that a later `relate_books()` does not overwrite.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_notebooks.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_relations.py -q`

---

## Test Specification

```python
# test_library.py
async def test_find_books_sectors_first(store, book_md): ...
async def test_find_books_merges_scopes_project_first(tmp_path, fake_adapter): ...
# test_notebooks.py (CREATE) — build a Bookstore like test_library.py's `store` fixture (copy the fixture; it is not in conftest)
async def test_relation_sheets_project_manual_edges(tmp_path, fake_adapter): ...
# test_relations.py
async def test_relate_books_keeps_manual_edges(...): ...
# test_mcp_server.py: update `assert len(server.tools) == 14` → 15; assert "bookstore_find_books" in description
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
9. **Close** with `parrot sdd task close TASK-5480 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
