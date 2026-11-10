---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — carried from sdd/proposals/bookstore-notebooks-shared-pageindex.brainstorm.md
tags: [bookstore, pageindex, mcp, local-toolkits, notebooks, catalog, ingest]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/bookstore-notebooks.md, wiki/knowledge/pageindex-local-mcp.md, wiki/knowledge/bookstore-graph.md]
  api_modules: [parrot.knowledge.bookstore.library, parrot.knowledge.bookstore.pageindex, parrot.knowledge.bookstore.notebooks, parrot.knowledge.pageindex.toolkit]
---

# Feature Specification: Bookstore Notebooks over a Shared PageIndex Store

**Feature ID**: FEAT-876
**Date**: 2026-11-10
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: next

> Source: `sdd/proposals/bookstore-notebooks-shared-pageindex.brainstorm.md` (accepted, Option A).
> Source paths below are relative to `packages/ai-parrot/src/parrot/` unless stated; line numbers
> were verified at `dev` @ `420bea2707` (origin) / `f3fa62968c` (local).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Bookstore is built **on top of** PageIndex: `Bookstore` composes one `PageIndexToolkit` per
library scope whose `storage_dir` is `<library>/trees/` (`knowledge/bookstore/library.py:331`,
`knowledge/bookstore/config.py:50`). Every `bookstore add` ends in `toolkit.create_tree(...)`; the
catalog (`library.db`) is a metadata layer over those trees (fichas, FTS5, sha256 identity,
relations, communities), not a second content index. PageIndex itself has no global index: every
consumer instantiates its own toolkit over its own directory, and the FEAT-842 local MCP server
serves `<repo>/.parrot/pageindex` only — its spec deliberately kept "the Bookstore server separate"
and "no user-level or shared library".

That leaves three gaps a user of both planes hits today (observed in the `parrot-bookstore` test
repository, where the PageIndex MCP had to be pointed by hand at `.parrot/library/trees`):

1. **Reading the library through PageIndex is possible but unguarded.** File-level two-writer
   safety exists (FEAT-831 per-tree `flock` + generation-signature reload), but the server also
   exposes every structural write — `create_tree`, `delete_tree`, `rename_tree`, `import_*`,
   `insert_*`, `vacuum_tree`, `optimize(apply=True)` — on trees the catalog believes it owns. One
   `rename_tree` leaves a card with a dangling `tree_name`. The only defence is hand-listing tools
   in the template's `exclude:`, and because the server serves "whatever `get_tools()` returns",
   every new tool reopens the hole.
2. **Annotations have nowhere safe to live.** The user wants the PageIndex *write* tools over
   ingested books to build richer knowledge: virtual footnotes on sections, reading notes,
   cross-book relation sheets, and a Dewey-style classification of the library. Written into the
   book's own tree they are lost on the next re-index (`add_book` with status `"updated"` rebuilds
   the tree from the source — the same loss class as the closed `issue:9013034b010f` for hand-edited
   cards), and they blur evidence with interpretation: the `bookstore` research skill tells the agent
   to "distinguish statements in the books from your interpretation", yet a note inside the book tree
   would be cited as *Book, "Section", pp. x–y*.
3. **A tree built elsewhere cannot become a book.** There is no way to register an existing
   PageIndex tree (from `.parrot/pageindex`, a free-hand tree an agent created, another repository)
   in the catalog without re-ingesting its source — and a notebook has no source to re-ingest.

**Users**: the human curating the library with the `bookstore` CLI and the PageIndex MCP write
tools; the research agent (Claude Code / Codex via the `bookstore` MCP and skill) that must answer
"which books of this library treat X, and where?" in two steps without reading the books.

### Goals

- **G1 — Evidence vs. notebook.** A book tree is immutable from the outside and re-indexable from
  its source. Notes, footnotes, relation sheets and classification live in separate *notebook*
  trees (`<slug>_notes` per book, `_library_notes` per scope) that re-index never touches.
- **G2 — One storage directory per scope.** Notebooks are ordinary PageIndex trees inside the same
  `<library>/trees/`, so one toolkit (Bookstore's own or an MCP server) sees books and notebooks
  alike. Registration is lazy, by naming convention: Bookstore creates the `kind=notes` catalog row
  the first time it reads a notebook; no component outside `Bookstore` writes `library.db`.
- **G3 — Bookstore-owned write policy, one server for both scopes.** A
  `LibraryPageIndexToolkit` facade in `parrot.knowledge.bookstore` serves the full `pageindex_*`
  tool surface over the project **and** the global library, routes each tree to its scope and
  enforces: book trees — every write denied; catalogued notebooks — `rename_tree`/`delete_tree`
  denied, everything else allowed; uncatalogued trees — allowed. `PageIndexToolkit` gains only a
  generic, policy-free hook (`write_tools`, `_authorize_write`, `read_only`); dependency direction
  stays `bookstore → pageindex`; the generic MCP machinery is untouched (a new packaged template
  `pageindex-library.yaml` is allowed).
- **G4 — Annotated reads.** `read_section` returns the section plus `annotations: [...]` anchored
  to that node; `get_toc` marks entries carrying footnotes. Anchors are
  `{book_id, scope, node_id, doc_id, revision}` stored in notebook node metadata via `tag_node`;
  after a book is `"updated"` they are remapped (same `doc_id`, new `revision`, matching section
  title) or flagged `stale`, never dropped.
- **G5 — Sectors are authoritative.** The library notebook is a Dewey-style sector tree whose nodes
  anchor books *and* the ToC entries where each book treats the subject. A new read tool
  `find_books(query)` answers "which books treat X?" in two steps (sector → books → anchored ToC
  entries) and labels its source; FTS over cards and Leiden communities remain fallback /
  suggestion only. The `bookstore` skill funnel starts with `find_books`.
- **G6 — Three ways to populate.** The human writes notebooks, the agent writes them on the human's
  instruction with the PageIndex tools, and `bookstore notebook draft` proposes sectors and
  anchors from cards, ToCs and communities (LLM when configured, communities 1:1 otherwise), never
  overwriting human-edited nodes.
- **G7 — Relation sheets feed the graph.** A notebook node anchoring two or more books projects into
  `book_relations` with `origin: "manual"`, `metadata.rel` within the existing `RelationKind`
  (default `parallels`, first anchor = source for directed kinds), weight `1.0`; manual edges are
  never overwritten by the LLM stage.
- **G8 — Import a tree.** `bookstore add --import <tree-name|path> [--as book|notes] [--for
  <book_id>]` copies an external tree into the library (original untouched) or adopts an
  uncatalogued in-library tree in place; `--as book` requires exactly one FEAT-840 document.
- **G9 — No-LLM and stdout discipline preserved.** Notes, anchors, `find_books`, import and the
  policy are deterministic; only drafting uses a model and degrades to communities. Both stdio
  servers keep stdout pure. Bookstore's MCP stays read-only (FEAT-533 §4).

### Non-Goals (explicitly out of scope)

- No annotations inside book trees and no re-index merge of foreign nodes (brainstorm Option B,
  rejected). No SQLite-only annotation overlay (Option C, rejected).
- No change to `mcp/toolkit_server.py`, `toolkit_seed.py`, `toolkit_install.py`, `hosts.py`,
  `local_cli.py`; the existing `pageindex.yaml` template is untouched.
- No multi-directory `PageIndexToolkit`; routing lives in the Bookstore facade.
- No write tool on the Bookstore MCP server.
- No splitting of a multi-document tree into N books on import; no `--move` on import (copy only).
- No `tag_node` on book trees (OKF typing happens at ingest); no new `RelationKind` and no change to
  `REL_WEIGHTS`.
- No OKF sidecar generation for notebooks; no wiki export changes beyond what `export_wiki`
  already projects from `book_relations`.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:cdc35cf9bc33fc89cd912a0bcd1265245f0f8323c9e13a8ed8a3c573e86b339a evaluation_digest=sha256:4492f02ce7478ef75964045fcbb367abcccca91de28dea8a8c6f5fda0720b55d rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools

## 2. Architectural Design

### Overview

Two kinds of tree share `<library>/trees/`, distinguished by a new catalog column `kind`
(`book` | `notes`) and a `notes_for` link:

- **Book notebook** — one per book, named `<book_id>_notes` (tree names must match
  `^[A-Za-z0-9_-]{1,128}$`, `knowledge/pageindex/content_store.py:41`; a single `_` also avoids the
  reserved `--staging-` marker, `library.py:73`). Created on demand by whoever writes first — the
  MCP (`pageindex_create_tree`) or Bookstore (`ensure_notebook`). Nodes are reading notes and
  *virtual footnotes*; a footnote's metadata (`tag_node(metadata=...)`) carries `note_kind` and
  one or more **anchors** into the book tree.
- **Library notebook** — one per scope, `_library_notes`. Its nodes are **sectors** in a
  Dewey-like hierarchy (`100 Philosophy › 170 Ethics › 171 Ethical theories`), each with
  `metadata.sector_code` and anchors to books (no `node_id`) and to ToC entries (`node_id`).
  Relation sheets (nodes anchoring ≥ 2 books) live here or in a book notebook.

**Registration is lazy, by convention — classification is not.** `Bookstore.notebook_for(book_id)`
/ `library_notebook(scope)` look for the conventional tree on disk (`JSONTreeStore` of that scope's
toolkit) and, when it exists but has no row, upsert a `kind=notes` card (`source_format: "tree"`,
`source_path` = the tree's JSON path, `source_sha256` = the snapshot hash defined under *Import*,
`card_origin: "fallback"`). The facade never writes `library.db`. The write policy, however, never
waits for that row: a tree is classified **by name and catalog together** — `_library_notes`, or
`<X>_notes` where `X` is a catalogued book, is a notebook from the moment it exists (or is being
created), so the registration gap cannot be used to rename or delete it (design-research S2).
Every existing read path that enumerates cards (`list_books`, `catalog_search`, `search`,
`resolve_book`, `related_books`, `relate_books`, `communities`, `doctor`, `export_wiki`,
`taken_slugs`) filters `kind='book'` unless it explicitly asks for notes; notebook rows fill the
NOT NULL source columns with the values above, so one table keeps the `tree_name UNIQUE` guard
and slug allocation working (S1). Identity is `(scope, book_id)` at every anchor/notebook boundary:
anchors carry `scope`, `annotations_for` and `find_books` resolve through it and report it, so a
global and a project book with the same id never share a notebook (S11).

**One server, both scopes.** `LibraryPageIndexToolkit(AbstractToolkit)` in
`knowledge/bookstore/pageindex.py` owns a `Bookstore` built from `resolve_locations(project_root)`,
exposes one delegating `async def` per PageIndex tool (same names → same `pageindex_*` tool names
through `tool_prefix`), resolves `(scope, toolkit)` for the target tree through the catalog
(project-first for uncatalogued names), applies the policy table below, then delegates to
`Bookstore._toolkit(scope)`. `create_tree` takes an optional `scope`; `list_trees` keeps
PageIndex's `list[str]` response schema (merged, de-duplicated names) and a new
`list_library_trees` returns `[{tree_name, scope, kind}]` (S6). `rename_tree` authorizes **both**
`src` and `dst` under one decision snapshot — a book may not be moved to a free name, and a free
tree may not be renamed onto a book or notebook name (S4). When the server has no `llm:` the facade
delegates `search`/`retrieve` with `use_llm_walk=self._store.has_llm`, because `Bookstore._toolkit`
hands PageIndex a `_NullAdapter` (`library.py:336`) that would otherwise make the default LLM walk
fail (S7). `PageIndexToolkit` itself stays single-`storage_dir`; it gains `write_tools`
(class-level, prefixed names, sibling of `llm_dependent_tools`), `_authorize_write(tree_name, op)`
(default no-op) and `read_only=True` (raises on write, hides `write_tools` from `get_tools()`), plus
the `PageIndexWriteDenied` error both layers raise. The hook sits at the common mutation boundary
`_mutate` (`toolkit.py:459`, used by every node op, `optimize(apply)` and `apply_plan`) **and** at
the top of the four direct-lock paths (`create_tree`, `delete_tree`, `rename_tree`, `vacuum_tree`)
plus `index_segments` and the `insert_*`/`import_*` entry points; a contract test asserts that every
public coroutine that takes `tree_lock` or calls `_mutate` is in `write_tools` (S3).

| Target tree | Structural ops (`delete_tree`, `rename_tree`, `insert_*`, `import_*`, `vacuum_tree`, `optimize(apply=True)`, `index_segments`) | Node ops (`add_node`, `update_node`, `update_node_content`, `delete_node`, `tag_node`) |
|---|---|---|
| catalogued `kind=book` | **denied** | **denied** |
| catalogued `kind=notes` | `rename_tree` / `delete_tree` **denied**; the rest allowed | allowed |
| not in the catalog | allowed | allowed |

**Annotated reads.** `Bookstore.annotations_for(book_id, node_id)` scans the book notebook's
nodes once per generation (cached by the tree's generation signature) and returns the notes anchored
to that node with `anchor_status ∈ {current, remapped, stale}`. `read_section` adds
`annotations: [...]`; `get_toc` adds `has_notes` per entry. Both are empty when no notebook exists,
so existing callers see no change. `remap_anchors(book_id)` runs after `add_book` returns
`"updated"`: an anchor whose `revision` is current stays `current`; otherwise the anchored node's
text is read from the **retained** old revision file (`SegmentStore.list_revisions`,
`segment_store.py:106`; revision files are immutable and survive re-index) and matched against the
new revision by content fingerprint, then by `(doc_id, title, nearest start_page)`; only a
**unique** match is rewritten (`remapped`), an ambiguous or absent match is `stale` (S9). Re-index
invalidation keeps manual edges: `_invalidate_graph` (`library.py:1960`) deletes only computed
origins (`deterministic`, `llm`, `community`); `origin="manual"` rows survive and are revalidated
when an anchored book is removed (S10).

**Sector retrieval.** `find_books(query, top_k)` searches every scope's `_library_notes` with the
toolkit's `search` (BM25; LLM walk when configured), merges project-first, resolves anchors against
the catalog, and returns `{source: "sectors", sectors: [{code, title, books: [{book_id, title,
scope, entries: [{node_id, title, start_page, end_page}]}]}]}`. No sector tree or no hit →
`source: "catalog_fts"` with today's `catalog_search` result and a `hint`. Communities are not
mixed in (they stay behind `communities` / `related_books`).

**Drafting.** `bookstore notebook draft --library [--scope] [--no-llm]` builds sector candidates
from `BookCard.topics/genre/traditions`, community labels and ToC titles; with an LLM, a
`SectorDraft` is requested per community; without one, communities map 1:1 to sectors. Draft nodes
carry `metadata.origin = "draft"`; nodes with any other origin are never overwritten.
`--book <id>` writes a reading-guide skeleton (one note per top-level ToC entry, empty body).

**Import.** `Bookstore.import_tree(source, scope, as_kind, notes_for, force)` copies the tree JSON,
its sidecar body directory and `segments/` (through `NodeContentStore` / `SegmentStore` paths, never
hand-globbed) into the scope's `trees/` under a Bookstore-allocated slug, under the same source/book
operation locks `add_book` uses. The copy is **staged** under a `--staging-` name (the marker
`add_book` already reserves, `library.py:73`), validated there (every body/segment reference
resolves; the one-document rule for `--as book`), then published atomically by the FEAT-831 rename
path, so a crash leaves at most a staging tree that the existing reserved-tree sweep removes (S8).
`source_sha256` is the hash of the **logical snapshot** — tree JSON plus the sorted
`(relative path, sha256)` manifest of body blobs and revision files — not of the JSON alone (S8).
An in-library uncatalogued name is adopted in place. `--as book` drafts a card from the tree
(`_draft_card` path) and requires exactly one document (`_document_of`, `library.py:687`, takes
`documents[0]`).

### Component Diagram
```
parrot-pageindex-library (stdio, template pageindex-library.yaml)
   └─ LibraryPageIndexToolkit (facade, tool_prefix "pageindex")
        ├─ Bookstore(resolve_locations(project_root))
        │     ├─ CatalogStore[project] ─ library.db (kind, notes_for)     ← read for policy, written only by Bookstore
        │     ├─ PageIndexToolkit[project] ─ .parrot/library/trees/   {book trees, <id>_notes, _library_notes}
        │     ├─ CatalogStore[global]  ─ ~/.parrot/library/library.db
        │     └─ PageIndexToolkit[global]  ─ ~/.parrot/library/trees/
        └─ policy: resolve(tree) → (scope, kind) → deny | delegate

parrot-bookstore (stdio, read-only)
   └─ BookstoreToolkit → Bookstore
        ├─ read_section ──→ annotations_for(book, node) ──→ <id>_notes (anchors, anchor_status)
        ├─ get_toc ───────→ has_notes per entry
        └─ find_books ────→ _library_notes[project] ⊕ _library_notes[global] → catalog → entries

bookstore CLI
   ├─ add --import ──→ Bookstore.import_tree
   ├─ notebook draft → notebooks.draft_library_notebook / draft_book_notebook → tag_node(origin=draft)
   ├─ relate --from-notes → notebooks.relation_sheets → CatalogStore.upsert_relations(origin=manual)
   ├─ list --notes / remove --with-notes / doctor --notes
   └─ add (existing) ──→ "updated" ──→ remap_anchors
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `knowledge/pageindex/toolkit.py::PageIndexToolkit` | extends | `write_tools`, `_authorize_write`, `read_only`, `PageIndexWriteDenied`; every write tool calls the hook first; `get_tools()` (`:713`) hides `write_tools` when `read_only` |
| `knowledge/bookstore/catalog.py::CatalogStore` | modifies | `kind`, `notes_for` columns via `_ADDED_COLUMNS` (`:95`); FTS `kind` column; `list_cards(kind=...)`, `notebook_for`, `library_notebook` |
| `knowledge/bookstore/models.py` | extends | `BookCard.kind`, `.notes_for`; `source_format` gains `"tree"`; `BookRelation.origin` gains `"manual"`; `Anchor`, `Annotation`, `SectorDraft` |
| `knowledge/bookstore/library.py::Bookstore` | extends | notebook lifecycle, `annotations_for`, `remap_anchors`, annotated `read_section`/`get_toc`, `find_books`, `import_tree`, `remove_book(with_notes)`, `doctor(notes=True)` |
| `knowledge/bookstore/toolkit.py::BookstoreToolkit` | extends | `find_books` added to `read_tools`; `read_section`/`get_toc` payloads carry the new keys |
| `knowledge/bookstore/mcp_server.py` | modifies | funnel description names `find_books` first |
| `knowledge/bookstore/relations.py` | uses | `deterministic_relations` untouched; manual edges enter through `CatalogStore.upsert_relations` |
| `knowledge/bookstore/cli.py` | extends | `add --import/--as/--for`, `notebook draft`, `relate --from-notes`, `list --notes`, `remove --with-notes`, `doctor --notes` |
| `mcp/_toolkit_templates/pageindex-library.yaml` | new | auto-discovered by `available_templates()` (`mcp/toolkit_seed.py:53`); served by the unchanged `create_toolkit_mcp_server` |
| `.claude/skills/bookstore/SKILL.md` + `.agents/skills/bookstore/SKILL.md` | modifies | funnel starts with `find_books`; cite notebooks as notes, never as book pages |

### Data Models
```python
# knowledge/bookstore/models.py (additions)
class Anchor(BaseModel):
    """One reference from a notebook node into a book (optionally into a node of it)."""
    book_id: str
    scope: Literal["project", "global"] = "project"
    node_id: Optional[str] = None
    doc_id: Optional[str] = None
    revision: Optional[str] = None

class Annotation(BaseModel):
    """A notebook node as returned next to a book section."""
    note_tree: str
    node_id: str
    title: str
    body: str
    note_kind: Literal["footnote", "note", "sector", "sheet"] = "note"
    origin: Literal["human", "agent", "draft"] = "human"
    anchor_status: Literal["current", "remapped", "stale"] = "current"

class SectorDraft(BaseModel):
    """LLM-proposed sector for the library notebook."""
    code: str
    title: str
    rationale: str = ""
    books: list[Anchor] = Field(default_factory=list)

# BookCard additions (defaults keep every existing row valid)
#   kind: Literal["book", "notes"] = "book"
#   notes_for: Optional[str] = None            # book_id (== tree_name) for a book notebook; None for _library_notes
#   source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx", "tree"]
# BookRelation.origin: Literal["deterministic", "llm", "community", "manual"]
```

Notebook node metadata (free-form dict on the PageIndex node, written with `tag_node`):
`{"note_kind": "footnote", "origin": "agent", "anchors": [Anchor...], "sector_code": "171", "rel": "parallels"}`.

### New Public Interfaces
```python
# knowledge/pageindex/toolkit.py
class PageIndexWriteDenied(PermissionError):
    """Raised when a write is refused by the toolkit's write policy."""

class PageIndexToolkit(AbstractToolkit):
    write_tools: frozenset[str]            # prefixed names of every mutating tool
    def __init__(..., read_only: bool = False, ...): ...
    def _authorize_write(self, tree_name: str, op: str) -> None: ...

# knowledge/bookstore/pageindex.py
class LibraryPageIndexToolkit(AbstractToolkit):
    """Full pageindex_* surface over the project + global libraries with Bookstore's write policy."""
    def __init__(self, project_root: Optional[str | Path] = None, llm_client=None,
                 lightweight_model: Optional[str] = None, max_result_chars: Optional[int] = None, **kwargs): ...

# knowledge/bookstore/library.py (Bookstore additions)
def notebook_for(self, book_id: str) -> Optional[BookCard]: ...
def library_notebook(self, scope: str) -> Optional[BookCard]: ...
async def ensure_notebook(self, book_id: Optional[str], scope: str) -> BookCard: ...
async def annotations_for(self, book_id: str, node_id: str) -> list[Annotation]: ...
async def remap_anchors(self, book_id: str) -> dict[str, int]: ...
async def find_books(self, query: str, top_k: int = 5) -> dict[str, Any]: ...
async def import_tree(self, source: str | Path, scope: str = "project", *, as_kind: str = "book",
                      notes_for: Optional[str] = None, title: Optional[str] = None, force: bool = False) -> tuple[BookCard, str]: ...

# knowledge/bookstore/notebooks.py
async def draft_library_notebook(store: Bookstore, scope: str, *, use_llm: bool = True) -> dict[str, Any]: ...
async def draft_book_notebook(store: Bookstore, book_id: str) -> dict[str, Any]: ...
async def relation_sheets(store: Bookstore, scope: Optional[str] = None) -> list[BookRelation]: ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: catalog & models | yes | columns via `_ADDED_COLUMNS`; FTS rebuild path exists; literals and defaults fixed above | — |
| M2: PageIndex write hook | yes | `write_tools` set fixed (every name in the policy table + `insert_ebook`, `insert_content`, `import_file`, `import_pdf`, `import_folder`); hook at the top of each; `read_only` hides via `exclude_tools` semantics | — |
| M3: facade + template | yes | one delegating coroutine per PageIndex tool, same signature; routing + policy table; template body given in §7 | — |
| M4: notebooks & anchors | no | remap heuristics (title match threshold, cache keyed by generation signature) need judgement | remap policy |
| M5: sectors, find_books, sheets | no | ranking/merge across scopes and the `rel` direction rule need judgement | ranking |
| M6: drafting | no | prompt + degradation path are design work | LLM contract |
| M7: import_tree | yes | copy set, lock order, identity fields and refusals fixed in §2 | — |
| M8: CLI | yes | options and messages fixed in §2/§7 | — |
| M9: docs & skill | yes | pages listed in §10; skill text rules in §7 | — |

### Module 1: Catalog schema & models for notebooks
- **Path**: `knowledge/bookstore/catalog.py`, `knowledge/bookstore/models.py`
- **Responsibility**: `kind`/`notes_for` columns and migration, FTS `kind` column, notebook
  accessors, model additions (`Anchor`, `Annotation`, `SectorDraft`, literals).
- **Depends on**: existing `CatalogStore`, `BookCard`.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/models.py  (modifies :152 BookCard, :172 source_format, :242 origin; adds classes)
  class Anchor(BaseModel): ...        # see §2 Data Models
  class Annotation(BaseModel): ...
  class SectorDraft(BaseModel): ...
  class BookCard(BaseModel):          # verified: models.py:152
      kind: Literal["book", "notes"] = "book"
      notes_for: Optional[str] = None

  # knowledge/bookstore/catalog.py  (modifies :95 _ADDED_COLUMNS, :64 _FTS_DDL, :286 _row_to_card, :300 upsert, :397 list_cards)
  class CatalogStore:                 # verified: catalog.py:163
      def list_cards(self, kind: Optional[str] = "book") -> list[BookCard]:
          """Cards of one kind (default books); ``None`` returns every row."""
      def notebook_for(self, book_id: str) -> Optional[BookCard]:
          """The ``kind='notes'`` row whose ``notes_for == book_id``, or None."""
      def library_notebook(self) -> Optional[BookCard]:
          """The ``kind='notes'`` row with ``notes_for IS NULL`` (tree ``_library_notes``), or None."""
  ```

### Module 2: PageIndex write-policy hook
- **Path**: `knowledge/pageindex/toolkit.py`
- **Responsibility**: `PageIndexWriteDenied`, class-level `write_tools`, `_authorize_write` called
  first in every mutating tool, `read_only` constructor flag (raise + hide).
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/toolkit.py  (modifies :220 class, :265 class attrs, :275 __init__, :713 get_tools, and each write tool)
  class PageIndexWriteDenied(PermissionError):
      """A write tool was refused for ``tree_name`` by the active write policy."""

  class PageIndexToolkit(AbstractToolkit):   # verified: toolkit.py:220
      write_tools: frozenset[str] = frozenset({
          "pageindex_create_tree", "pageindex_delete_tree", "pageindex_rename_tree", "pageindex_vacuum_tree",
          "pageindex_optimize", "pageindex_index_segments", "pageindex_insert_markdown", "pageindex_insert_ebook",
          "pageindex_insert_content", "pageindex_import_file", "pageindex_import_pdf", "pageindex_import_folder",
          "pageindex_tag_node", "pageindex_add_node", "pageindex_update_node", "pageindex_update_node_content",
          "pageindex_delete_node",
      })
      def __init__(self, adapter=None, storage_dir=None, ..., read_only: bool = False, ...): ...  # verified: toolkit.py:275
      def _authorize_write(self, tree_name: str, op: str) -> None:
          """Hook called before any tree lock is taken: inside ``_mutate`` (toolkit.py:459) for every node op and
          apply path, and at the top of create_tree/delete_tree/rename_tree/vacuum_tree/index_segments and the
          insert_*/import_* entry points. Default: allow; ``read_only`` raises PageIndexWriteDenied.
          ``op`` is the unprefixed tool name; rename passes ``op="rename_tree"`` once per endpoint."""
      def get_tools(self, ...):                     # verified: toolkit.py:713
          """Unchanged contract; additionally drops ``write_tools`` when ``read_only``."""
  ```
  `optimize(apply=False)` is a read (plan); only `apply=True` consults the hook with `op="optimize"`.
  `list_trees` keeps returning `list[str]` (`toolkit.py:741`).

### Module 3: `LibraryPageIndexToolkit` facade + `pageindex-library` template
- **Path**: `knowledge/bookstore/pageindex.py` (new), `mcp/_toolkit_templates/pageindex-library.yaml` (new)
- **Responsibility**: the full `pageindex_*` surface over both scopes, routing, policy table.
- **Depends on**: M1 (`kind`), M2 (`PageIndexWriteDenied`), existing `Bookstore`.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/pageindex.py  (new)
  class LibraryPageIndexToolkit(AbstractToolkit):     # AbstractToolkit verified: tools/toolkit.py (BookstoreToolkit pattern, bookstore/toolkit.py:30)
      """pageindex_* tools over the project + global libraries, with Bookstore's write policy."""
      name = "pageindex-library"
      tool_prefix = "pageindex"
      llm_dependent_tools: frozenset[str] = PageIndexToolkit.llm_dependent_tools   # verified: pageindex/toolkit.py:265
      def __init__(self, project_root: Optional[str | Path] = None, llm_client: Optional[AbstractClient] = None,
                   lightweight_model: Optional[str] = None, max_result_chars: Optional[int] = None, **kwargs: Any) -> None:
          """Builds ``Bookstore(resolve_locations(project_root), adapter=..., lightweight_model=...)``.
          ``llm_client`` is what ``create_toolkit_mcp_server`` passes (mcp/toolkit_server.py:338)."""
      def _resolve(self, tree_name: str) -> tuple[str, Optional[BookCard], str, PageIndexToolkit]:
          """(scope, card-or-None, kind, scope toolkit). kind ∈ {book, notes, free}: a catalogued row decides;
          otherwise ``_library_notes`` / ``<catalogued book>_notes`` is ``notes`` even without a row (S2);
          an uncatalogued name resolves project-first, then global if the tree exists there, else project."""
      def _authorize(self, tree_name: str, op: str) -> None:
          """Policy table of §2; raises PageIndexWriteDenied with the ``…_notes`` hint for book trees."""
      async def list_trees(self) -> list[str]:
          """Same schema as PageIndexToolkit.list_trees (toolkit.py:741): merged, de-duplicated names."""
      async def list_library_trees(self) -> list[dict[str, Any]]:
          """``[{tree_name, scope, kind}]`` — the scoped listing (new tool, S6)."""
      async def create_tree(self, tree_name: str, scope: str = "project", **kwargs: Any) -> dict[str, Any]: ...
      async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:
          """Authorizes ``src`` AND ``dst`` (S4) before delegating; both must resolve to the same scope."""
      async def search(self, tree_name: str, query: str, top_k: int = 20, use_bm25: bool = True,
                       use_llm_walk: Optional[bool] = None, **kwargs: Any) -> list[dict[str, Any]]:
          """``use_llm_walk`` defaults to ``self._store.has_llm`` (S7; _NullAdapter at library.py:336)."""
      # …one delegating coroutine per remaining PageIndexToolkit tool, same name and parameters…
  ```
  ```yaml
  # mcp/_toolkit_templates/pageindex-library.yaml  (new)
  # parrot:summary: PageIndex tools over the Bookstore library (project + global) — books read-only, notebooks writable.
  # parrot:requires_llm: false
  # parrot:requires_dist: bm25s,pymupdf
  # parrot:requires_pip: ai-parrot[bookstore]
    pageindex-library:
      class: parrot.knowledge.bookstore.pageindex.LibraryPageIndexToolkit
      kwargs:
        project_root: {{repo_root}}
        max_result_chars: 24000
      # llm: anthropic:claude-haiku-5-5
      exclude: [pageindex_agentic_retrieve]
      env: {}
  ```

### Module 4: Notebook lifecycle, anchors and annotated reads
- **Path**: `knowledge/bookstore/library.py`
- **Responsibility**: lazy registration, `ensure_notebook`, `annotations_for` (+ generation-keyed
  cache), `remap_anchors`, `read_section`/`get_toc` payload keys, `remove_book(with_notes)`,
  `doctor(notes=True)`; call `remap_anchors` after an `"updated"` `add_book`.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/library.py  (modifies :613 list_books, :638 get_toc, :664 read_section, :1507 add_book, :1973 remove_book, :474 doctor)
  class Bookstore:                                   # verified: library.py:264
      def notebook_for(self, book_id: str) -> Optional[BookCard]:
          """Registered or on-disk ``<book_id>_notes`` (lazy upsert of the ``kind='notes'`` row)."""
      def library_notebook(self, scope: str) -> Optional[BookCard]:
          """Same for ``_library_notes`` of ``scope``."""
      async def ensure_notebook(self, book_id: Optional[str], scope: str = "project") -> BookCard:
          """Create the conventional tree when missing (``create_tree`` on the scope toolkit) and register it."""
      async def annotations_for(self, book_id: str, node_id: str) -> list[Annotation]:
          """Notes anchored to ``(book_id, node_id)``; ``[]`` when no notebook. Cached per notebook generation signature."""
      async def remap_anchors(self, book_id: str) -> dict[str, int]:
          """After re-index: current revision → ``current``; else read the anchored node's text from the retained old
          revision file (SegmentStore.list_revisions, segment_store.py:106), fingerprint-match it in the new revision,
          then (doc_id, title, nearest start_page); a UNIQUE match rewrites node_id/revision → ``remapped``;
          ambiguous or absent → ``stale``. Never deletes. Returns counts (S9)."""
      def _invalidate_graph(self, book_id: str) -> None:        # verified: library.py:1960
          """Now deletes only origins deterministic/llm/community; manual edges survive re-index (S10)."""
      def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:   # verified: library.py:664
          """Unchanged keys + ``annotations: list[dict]``."""
      def get_toc(self, book_id: str) -> dict[str, Any]:                        # verified: library.py:638
          """Unchanged keys + ``has_notes: bool`` per entry."""
      async def remove_book(self, book_id: str, *, with_notes: bool = False) -> bool:   # verified: library.py:1973
          """Default keeps the notebook (row kept, ``notes_for`` cleared → orphan notes); ``with_notes`` removes both."""
  ```
  Note: `read_section` is sync today (`:664`); the annotation lookup must stay sync (notebook
  tree read via the content store / tree store, no `await`) or `read_section` becomes async and
  `BookstoreToolkit.read_section` (`bookstore/toolkit.py:169`) awaits it — the task decides, the
  tool contract is unchanged either way.

### Module 5: Sectors, `find_books` and relation sheets
- **Path**: `knowledge/bookstore/library.py`, `knowledge/bookstore/toolkit.py`,
  `knowledge/bookstore/mcp_server.py`, `knowledge/bookstore/notebooks.py` (`relation_sheets`)
- **Responsibility**: two-step retrieval; manual edges from sheets.
- **Depends on**: M1, M4.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/library.py
  async def find_books(self, query: str, top_k: int = 5) -> dict[str, Any]:
      """{source: 'sectors'|'catalog_fts', sectors: [...], books: [...], hint?}. Sectors from every scope's
      ``_library_notes`` via ``PageIndexToolkit.search`` (toolkit.py:1743), merged project-first; never reads bodies."""

  # knowledge/bookstore/toolkit.py  (modifies :39 read_tools; adds method)
  async def find_books(self, query: str, top_k: int = 5) -> dict[str, Any]:
      """Which books of the library treat ``query``, and where — librarian's sectors first, catalog FTS as fallback."""

  # knowledge/bookstore/notebooks.py
  async def relation_sheets(store: Bookstore, scope: Optional[str] = None) -> list[BookRelation]:
      """Every notebook node anchoring ≥ 2 books → BookRelation(origin='manual', rel=metadata.rel or 'parallels',
      weight=1.0, rationale=body); directed kinds: first anchor is src."""
  ```
  `relate_books` (`library.py:1157`) must skip overwriting rows with `origin == "manual"`.

### Module 6: Notebook drafting
- **Path**: `knowledge/bookstore/notebooks.py` (new)
- **Responsibility**: `draft_library_notebook`, `draft_book_notebook`, `SectorDraft` prompt,
  no-LLM degradation (communities 1:1), never overwrite non-draft nodes.
- **Depends on**: M1, M4; `Bookstore.communities()` (`library.py:1408`), `_draft_card` LLM path.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/notebooks.py  (new)
  async def draft_library_notebook(store: Bookstore, scope: str = "project", *, use_llm: bool = True) -> dict[str, Any]:
      """Propose sectors + anchors into ``_library_notes``; returns {created, updated, skipped_human} counts."""
  async def draft_book_notebook(store: Bookstore, book_id: str) -> dict[str, Any]:
      """Reading-guide skeleton: one ``note`` per top-level ToC entry, anchored, empty body, origin='draft'."""
  ```

### Module 7: Import a tree
- **Path**: `knowledge/bookstore/library.py`
- **Responsibility**: `import_tree` (copy or adopt-in-place, as book or notes, identity fields,
  refusals), reusing `add_book`'s lock and publish path.
- **Depends on**: M1, M4.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/library.py  (adds next to :1507 add_book)
  async def import_tree(self, source: str | Path, scope: str = "project", *, as_kind: Literal["book", "notes"] = "book",
                        notes_for: Optional[str] = None, title: Optional[str] = None, force: bool = False) -> tuple[BookCard, str]:
      """``source``: a tree JSON path outside the library (copied; original untouched) or an uncatalogued tree name
      inside it (adopted in place). Status ``added`` | ``adopted`` | ``skipped`` (same sha). Raises BookstoreError when
      ``as_kind='book'`` and the tree has != 1 document, when a ``_notes`` tree is imported without ``as_kind='notes'``,
      or when ``notes_for`` already has a notebook and not ``force`` (then the old one is renamed ``<id>_notes_<ts>``)."""
  ```

### Module 8: CLI surface
- **Path**: `knowledge/bookstore/cli.py`
- **Responsibility**: `add --import/--as/--for`, `notebook` group (`draft --library|--book`,
  `--scope`, `--no-llm`), `relate --from-notes`, `list --notes`, `remove --with-notes`,
  `doctor --notes`.
- **Depends on**: M4–M7.
- **Interface Skeleton**:
  ```python
  # knowledge/bookstore/cli.py  (modifies :103 add, :248 list, :450 relate, :710 doctor, :778 remove; adds group)
  @bookstore.group("notebook")
  def notebook() -> None: """Notebooks: per-book notes and the library's sector index."""
  @notebook.command("draft")   # --library | --book <id>, --global, --no-llm, --json
  ```

### Module 9: Documentation & skill
- **Path**: `wiki/knowledge/bookstore-notebooks.md` (new), `wiki/knowledge/pageindex-local-mcp.md`,
  `wiki/knowledge/bookstore-graph.md`, `.claude/skills/bookstore/SKILL.md`, `.agents/skills/bookstore/SKILL.md`
- **Responsibility**: pages in §10; skill funnel starts at `find_books`; citation rule for notes.
- **Depends on**: M3–M7 (content).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_catalog_kind_migration_keeps_existing_rows` | M1 | old `library.db` opens; every row reads `kind="book"`, `notes_for=None` |
| `test_list_cards_default_excludes_notes` | M1 | `list_cards()` vs `list_cards(kind=None)` |
| `test_write_tools_matches_every_mutating_tool` | M2 | each tool whose body takes `tree_lock` or writes is in `write_tools`; no read tool is |
| `test_read_only_hides_and_refuses` | M2 | `get_tools()` has no `write_tools`; direct call raises `PageIndexWriteDenied` |
| `test_authorize_write_called_before_lock` | M2 | monkeypatched hook raising → no lock taken, tree unchanged |
| `test_facade_serves_same_names_as_pageindex_toolkit` | M3 | set equality of `get_tools()` names (minus llm-dependent when no llm) |
| `test_facade_routes_global_tree` | M3 | catalogued global book resolves to the global toolkit |
| `test_facade_denies_book_tree_with_hint` | M3 | `add_node` on a book → `PageIndexWriteDenied` naming `<id>_notes` |
| `test_facade_denies_rename_of_notebook` | M3 | `rename_tree` on `kind=notes` denied; `add_node` allowed |
| `test_facade_rename_authorizes_both_endpoints` | M3 | free → book name denied; book → free name denied (S4) |
| `test_facade_classifies_unregistered_notebook_by_name` | M3 | `<book>_notes` with no row: rename/delete denied, node ops allowed (S2) |
| `test_facade_no_llm_filtering_matches_pageindex` | M3 | without `llm:` the served set equals the plain server's; `search` runs BM25 only (S7) |
| `test_facade_list_trees_schema_unchanged` | M3 | `list_trees` is `list[str]`; `list_library_trees` carries scope/kind (S6) |
| `test_facade_allows_free_tree` | M3 | uncatalogued tree fully writable |
| `test_template_pageindex_library_seeds_and_serves` | M3 | template discovered, section seeded, stdio handshake lists `pageindex_*` |
| `test_notebook_lazy_registration` | M4 | tree created via toolkit → `notebook_for` upserts the row once |
| `test_read_section_carries_annotations` | M4 | footnote anchored to node → returned; other node → `[]` |
| `test_get_toc_has_notes` | M4 | flag per entry |
| `test_remap_anchors_after_update` | M4 | re-index → `remapped` on a unique content match, `stale` otherwise, nothing dropped |
| `test_remap_repeated_titles_and_moved_sections` | M4 | duplicate headings → `stale`, moved section → `remapped` by fingerprint (S9) |
| `test_reindex_keeps_manual_relations` | M4/M5 | `_invalidate_graph` leaves `origin="manual"` rows (S10) |
| `test_annotations_resolve_by_scope_and_id` | M4 | same `book_id` in project and global → each sees only its own notebook (S11) |
| `test_remove_book_keeps_notebook_by_default` | M4 | `with_notes` removes both |
| `test_find_books_sectors_first` | M5 | sector hit → `source="sectors"` with entries; no tree → `catalog_fts` + hint |
| `test_find_books_merges_scopes_project_first` | M5 | both `_library_notes` consulted |
| `test_relation_sheets_project_manual_edges` | M5 | `origin="manual"`, default `parallels`, direction rule; `relate_books` keeps them |
| `test_draft_library_without_llm_uses_communities` | M6 | 1:1 sectors, `origin="draft"` |
| `test_draft_never_overwrites_human_nodes` | M6 | human node untouched on re-draft |
| `test_import_tree_copies_and_cards` | M7 | JSON + sidecar + segments copied; `source_format="tree"`; original intact |
| `test_import_tree_adopts_in_place` | M7 | in-library name → `adopted`, no copy |
| `test_import_tree_refuses_multi_document_as_book` | M7 | hint text; `--as notes` accepted |
| `test_import_tree_stages_and_publishes_atomically` | M7 | forced failure mid-copy leaves only a `--staging-` tree, no catalog row; sweep removes it (S8) |
| `test_import_tree_sha_covers_bodies_and_segments` | M7 | changing a body blob changes `source_sha256` (S8) |
| `test_cli_add_import_and_notebook_draft` | M8 | options wired; `--json` shapes |
| `test_skill_text_funnel_starts_with_find_books` | M9 | both skill twins |

### Integration Tests
| Test | Description |
|---|---|
| `test_mcp_write_then_bookstore_read` | note written through `LibraryPageIndexToolkit` is visible to `BookstoreToolkit.read_section` in the same process (generation reload) |
| `test_two_servers_one_library_stdio` | `parrot mcp-local pageindex-library` + `bookstore mcp` over one `tmp` library: write note over stdio, read annotated section over stdio, stdout pure |
| `test_reindex_preserves_notebook_end_to_end` | `add_book` (updated) → notebook intact, anchors remapped, `find_books` still answers |
| `test_concurrent_notebook_writes_and_reads` | concurrent `add_node`/`tag_node` through the facade while `read_section` loops: no torn annotation list, exactly one `kind=notes` row (S12) |
| `test_project_and_global_lookups_under_concurrency` | both scopes written and read concurrently; provenance (`scope`) never crosses (S11/S12) |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/bookstore/test_library.py
- packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py
- packages/ai-parrot/tests/knowledge/bookstore/test_models.py
- packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py
- packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py
- packages/ai-parrot/tests/knowledge/bookstore/test_cli.py
- packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py
- packages/ai-parrot/tests/knowledge/bookstore/test_relations.py
- packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py
- packages/ai-parrot/tests/knowledge/bookstore/test_skill_text.py
- packages/ai-parrot/tests/mcp/test_pageindex_template.py
markers: none

### Test Data / Fixtures
```python
# reuse packages/ai-parrot/tests/knowledge/bookstore/conftest.py (`store`, `book_md`, `locations`, `fake_adapter`)
@pytest.fixture
def two_scope_locations(tmp_path, monkeypatch):
    """project + global LibraryLocation under tmp_path; PARROT_LIBRARY_DIR / PARROT_HOME monkeypatched."""

@pytest.fixture
async def notebook_with_footnote(store, book_md):
    """add_book(book_md) → ensure_notebook → add_node + tag_node(anchors=[first ToC node]) → (card, note_id)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Validation Contract tests pass; new tests in §4 exist and pass.
- [ ] Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).
- [ ] An existing `library.db` opens after upgrade; every pre-existing row has `kind="book"`; `bookstore list` output is unchanged (G1/G2).
- [ ] A tree named `<book_id>_notes` created through the facade appears in `bookstore list --notes` and in `read_section(...).annotations` without any CLI step; `library.db` is only ever written by `Bookstore` (G2).
- [ ] `parrot toolkits install pageindex-library` seeds the section and `parrot mcp-local pageindex-library` lists the same `pageindex_*` names as the plain `pageindex` server (minus LLM-dependent ones without `llm:`), over both the project and the global library (G3).
- [ ] On a catalogued book tree every write tool raises `PageIndexWriteDenied` naming `<book_id>_notes`; on a catalogued notebook `rename_tree`/`delete_tree` raise and node ops succeed; an uncatalogued tree is fully writable (G3).
- [ ] `PageIndexToolkit(read_only=True).get_tools()` contains none of `write_tools`, and `write_tools` covers every tool that takes `tree_lock` or persists (G3).
- [ ] `mcp/toolkit_server.py`, `toolkit_seed.py`, `toolkit_install.py`, `hosts.py`, `local_cli.py` and `pageindex.yaml` are byte-identical to `origin/dev` (Non-Goals).
- [ ] After `add_book` returns `"updated"`, no notebook node is deleted; anchors are `current`, `remapped` or `stale` (G4).
- [ ] `find_books` returns `source="sectors"` with ToC entries when a sector matches, `source="catalog_fts"` + hint otherwise; it never reads a book body (G5).
- [ ] `bookstore notebook draft --library --no-llm` on a library with communities creates one sector per community with `origin="draft"`; re-running after a human edit leaves the edited node intact (G6).
- [ ] `bookstore relate --from-notes` writes `origin="manual"` edges that a later `bookstore relate --all` does not overwrite (G7).
- [ ] `bookstore add --import <path>` copies the tree and leaves the original byte-identical; `--as book` refuses a 0- or N-document tree with the documented hint; an in-library uncatalogued name is adopted in place (G8).
- [ ] Both stdio servers pass the existing stdout-purity tests; every new path works with no `PARROT_BOOKSTORE_LLM` (G9).
- [ ] No breaking change: existing `read_section` / `get_toc` keys unchanged (new keys additive); `BookstoreToolkit.read_tools` grows by exactly `find_books`; `pageindex_list_trees` keeps its `list[str]` schema on both servers.
- [ ] Every card-enumerating read path (`list_books`, `catalog_search`, `search`, `resolve_book`, `related_books`, `relate_books`, `communities`, `doctor`, `export_wiki`, `taken_slugs`) excludes `kind="notes"` rows unless asked for them (S1).
- [ ] `rename_tree` through the facade refuses either endpoint that is a book, and refuses moving a free tree onto a book or notebook name (S4).
- [ ] An interrupted `import_tree` leaves no catalog row and at most a `--staging-` tree (S8); `_invalidate_graph` after re-index leaves `origin="manual"` rows in place (S10).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER   # verified: knowledge/bookstore/library.py:35
from parrot.knowledge.pageindex.content_store import NodeContentStore               # verified: library.py:31
from parrot.knowledge.pageindex.locks import TreeLockTimeout, tree_lock             # verified: library.py:33
from parrot.knowledge.pageindex.segments import RevisionMismatchError               # verified: library.py:34
from parrot.knowledge.bookstore.catalog import CatalogStore, merged_cards, merged_communities, merged_relations, merged_search  # verified: library.py:46
from parrot.knowledge.bookstore.config import LibraryLocation                       # verified: library.py:47
from parrot.knowledge.bookstore.config import resolve_locations                     # verified: config.py:79 (used by cli.py / mcp_server.py)
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError            # verified: library.py:264, :197
from parrot.knowledge.bookstore.models import BookCard, BookRelation, TocEntry, CardDraft, RelationKind, REL_WEIGHTS  # verified: models.py:152, :210, :98, :117, :39, :83
from parrot.tools.toolkit import AbstractToolkit                                    # verified: knowledge/bookstore/toolkit.py:25
from parrot.knowledge.pageindex import PageIndexToolkit                             # verified: knowledge/pageindex/__init__.py:21, __all__ :51
```

### Existing Class Signatures
```python
# knowledge/bookstore/library.py
_STAGING_MARKER = "--staging-"                                     # line 73
def _is_reserved_tree_name(name: str) -> bool                       # line 158
class Bookstore:                                                    # line 264
    def __init__(self, locations: list[LibraryLocation], adapter=None, lightweight_model=None, ...)  # line 278
    locations: list[LibraryLocation]; adapter; lightweight_model     # set in __init__
    def has_llm(self) -> bool                                        # line 313 (property)
    def _toolkit(self, scope: str) -> PageIndexToolkit              # line 331  (PageIndexToolkit(adapter=self.adapter if not None else _NullAdapter(), storage_dir=loc.trees_dir, ...) — _NullAdapter at :336)
    async def search_book(...)                                       # line 648 (passes use_llm_walk=self.has_llm at :661)
    def _invalidate_graph(self, book_id: str) -> None                # line 1960 (calls store.delete_relations(book_id=book_id) at :1969 — NO origin filter today)
    def _content_store(self, scope: str) -> NodeContentStore        # line 387
    async def doctor(self, scope=None, *, repair=False, relate=False, use_llm=True, ...) -> dict  # line 474
    def list_books(self) -> list[BookCard]                           # line 613 (merged_cards, project wins)
    def catalog_search(self, query: str, top_k: int = 8) -> list[BookCard]   # line 617
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]  # line 621
    def get_toc(self, book_id: str) -> dict[str, Any]                # line 638
    def read_section(self, book_id: str, node_id: str) -> dict[str, Any]      # line 664 (sync; keys: book_id, book_title, node_id, title, start_page, end_page, content)
    async def _document_of(self, card, toolkit) -> dict[str, Any]    # line 687 (documents[0]; raises BookstoreError when none)
    async def relate_books(...)                                      # line 1157
    def communities(self) -> list[BookCommunity]                     # line 1408
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None, force=False, *, relate=False) -> tuple[BookCard, str]  # line 1507
    async def remove_book(self, book_id: str) -> bool                # line 1973
    async def optimize_book(...)                                     # line 2003

# knowledge/bookstore/catalog.py
_BOOKS_DDL  # line 42 — columns: book_id, title, authors, year, language, topics, summary, toc_digest, toc, tree_name UNIQUE, source_path, source_sha256, source_format, page_count, chapter_count, added_at, card_origin
_FTS_DDL    # line 64 — books_fts(book_id UNINDEXED, title, authors_text, topics_text, summary, toc_digest, genre, traditions_text)
_ADDED_COLUMNS: list[tuple[str, str]]   # line 95 — ALTER TABLE migration list consumed by _ensure_schema
class CatalogStore:                     # line 163
    def _ensure_schema(self, conn) -> None          # line 197 (WAL; ALTER TABLE for _ADDED_COLUMNS; FTS rebuild path)
    def _row_to_card(row) -> BookCard               # line 286 (staticmethod)
    def upsert(self, card: BookCard) -> None        # line 300
    def remove(self, book_id: str) -> bool          # line 357
    def list_cards(self) -> list[BookCard]          # line 397
    def taken_slugs(self) -> set[str]               # line 403
    def search(self, query, top_k=8) -> list[tuple[BookCard, float]]   # line 409
    def upsert_relations(self, relations: list[BookRelation]) -> None  # line 496
    def delete_relations(self, book_id: Optional[str] = None, origin: Optional[str] = None) -> int   # line 526

# knowledge/bookstore/models.py
RelationKind = Literal["same_author", "shares_topic", "same_tradition", "same_genre", "same_era", "same_language", "influenced_by", "responds_to", "parallels", "contrasts_with", "same_community", ...]  # line 39
REL_WEIGHTS: dict[str, float]           # line 83
class TocEntry(BaseModel)               # line 98  (node_id, title, depth, start_page, end_page)
class CardDraft(BaseModel)              # line 117
class BookCard(BaseModel)               # line 152 — book_id == tree_name invariant (docstring :155)
    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx"]   # line 172
    card_origin: Literal["llm", "fallback", "manual"] = "llm"           # line 176
class BookRelation(BaseModel)           # line 210
    origin: Literal["deterministic", "llm", "community"]                # line 242

# knowledge/bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit)  # line 30 — name="bookstore", tool_prefix="bookstore"
    read_tools: frozenset[str]           # line 39 (14 names)
    async def get_toc(self, book_id)     # line 104
    async def read_section(self, book_id, node_id)   # line 169
    async def related_books(...)         # line 250
    async def search(...)                # line 321

# knowledge/bookstore/mcp_server.py
def create_bookstore_mcp_server(locations, adapter=None, lightweight_model=None) -> StdioMCPServer  # line 62
    description = (...)                  # line 93 (funnel text)
    server.register_tools(tools)         # line 110

# knowledge/bookstore/cli.py
def bookstore() -> None                  # line 99 (click group)
@bookstore.command("add") / def add(     # lines 103 / 117
@bookstore.command("list")               # line 248
@bookstore.command("relate")             # line 450
@bookstore.command("optimize")           # line 570
@bookstore.command("doctor")             # line 710
@bookstore.command("remove")             # line 778

# knowledge/bookstore/config.py
class LibraryLocation                    # line 33 — .db_path (:45) = root/"library.db"; .trees_dir (:50) = root/"trees"
def resolve_locations(cwd=None, include_global=True, require_exists=False) -> list[LibraryLocation]  # line 79

# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit)  # line 220 — name="pageindex", tool_prefix="pageindex"
    llm_dependent_tools: frozenset[str]  # line 265
    def __init__(self, adapter=None, storage_dir=None, reranker=None, lightweight_model=None, model=None, ..., generation_grace_s=3600, lock_timeout_s=30.0, ..., max_result_chars=None, ...)  # line 275 (ValueError without storage_dir)
    async def _mutate(self, tree_name, apply)                # line 459 (common locked mutation boundary used at :1533, :1710, :2006, :2090, :2160, :2318, :2665, :2730, :2763, :2817)
    def get_tools(self, ...)             # line 713 (override)
    async def list_trees(self) -> list[str]                 # line 741 (returns self._store.list_names())
    async def create_tree(...)                              # line 745
    async def delete_tree(self, tree_name)                  # line 781
    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]   # line 800
    async def index_segments(self, tree_name, node_id=None) # line 1456
    async def optimize(...)                                 # line 1541 (apply flag)
    async def vacuum_tree(self, tree_name, max_age_s=None)  # line 1717
    async def search(...)                                   # line 1743
    async def tag_node(self, tree_name, node_id, categories=None, metadata=None)  # line 1958 (metadata merged shallowly)
    async def insert_markdown(...) / insert_ebook / insert_content   # lines 2014 / 2093 / 2169
    async def import_file / import_pdf / import_folder      # lines 2193 / 2212 / 2552
    async def delete_node / add_node / update_node_content / update_node   # lines 2643 / 2674 / 2737 / 2770

# knowledge/pageindex/schemas.py
class PageIndexNode(BaseModel)           # line 118 — doc_id (:129), revision (:130), locked, locked_reason, aliases, key_items

# knowledge/pageindex/content_store.py
_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")   # line 41

# knowledge/pageindex/segment_store.py
class SegmentStore                       # line 25 — <storage_dir>/<tree>/segments/<doc_id>.<revision>.json (revision files are immutable)
    def list_revisions(self, tree_name: str) -> list[tuple[str, str]]   # line 106
    def delete_tree(self, tree_name: str) -> int                         # line 168

# tools/toolkit.py
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()  # line 262
    tool_prefix: str | None = None       # line 276
    llm_dependent_tools: frozenset = frozenset()   # line 313
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]   # line 522
    def _generate_tools(self) -> None    # line 575

# mcp/toolkit_seed.py
def available_templates() -> tuple[str, ...]   # line 53 — globs _toolkit_templates/*.yaml
# mcp/toolkit_server.py — create_toolkit_mcp_server: drop_tools = toolkit_cls.llm_dependent_tools when no llm (:335); kwargs["llm_client"] (:338-343); include/exclude filtering (:351-374)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LibraryPageIndexToolkit` | `Bookstore._toolkit(scope)` | delegation | `library.py:331` |
| `LibraryPageIndexToolkit._authorize` | `CatalogStore.get()` / `notebook_for()` | read | `catalog.py:374` (`get`), M1 |
| `PageIndexToolkit._authorize_write` | every write tool | call before `tree_lock` | `toolkit.py:745…2770` |
| `Bookstore.annotations_for` | `PageIndexToolkit.tag_node` metadata | node metadata read | `toolkit.py:1958` |
| `Bookstore.find_books` | `PageIndexToolkit.search` | BM25 / LLM walk | `toolkit.py:1743` |
| `relation_sheets` | `CatalogStore.upsert_relations` | write | `catalog.py:496` |
| `Bookstore.import_tree` | `NodeContentStore`, `SegmentStore`, `tree_lock` | copy + lock + publish | `library.py:31,33`; `segment_store.py:25` |
| template `pageindex-library.yaml` | `available_templates()` / `create_toolkit_mcp_server` | auto-discovery | `toolkit_seed.py:53`; `toolkit_server.py:338` |

### Does NOT Exist (Anti-Hallucination)
- ~~`books.kind` / `books.notes_for`~~ — not in `_BOOKS_DDL` nor `_ADDED_COLUMNS` today.
- ~~`PageIndexToolkit.write_tools` / `_authorize_write` / `read_only` / `PageIndexWriteDenied`~~ — new (M2).
- ~~`parrot.knowledge.bookstore.pageindex` / `LibraryPageIndexToolkit`~~ — new module (M3).
- ~~`parrot.knowledge.bookstore.notebooks`~~ — new module (M6).
- ~~`Bookstore.notebook_for` / `library_notebook` / `ensure_notebook` / `annotations_for` / `remap_anchors` / `find_books` / `import_tree`~~ — new.
- ~~`BookstoreToolkit.find_books`~~ — new; `read_tools` has 14 names today.
- ~~`bookstore add --import`, `bookstore notebook`, `relate --from-notes`, `list --notes`, `remove --with-notes`, `doctor --notes`~~ — no such options.
- ~~`BookRelation.origin == "manual"`~~, ~~`source_format == "tree"`~~ — literals have 3 / 6 values today.
- ~~`TreeNode`~~ — the node model is `PageIndexNode`.
- ~~`mcp/_toolkit_templates/pageindex-library.yaml`~~ — ten templates exist today, none for the library.
- ~~a multi-`storage_dir` `PageIndexToolkit` or a global PageIndex registry~~ — PageIndex is `storage_dir`-scoped.
- ~~a `parrot-pageindex` entry in this repo's `.mcp.json`~~ — only `bookstore` is registered here.
- ~~`wiki/knowledge/bookstore-notebooks.md`~~ — to create; `wiki/knowledge/bookstore.md` does not exist either (Bookstore pages: `bookstore-graph.md`, `bookstore-agentic-retrieval.md`, `bookstore-codex.md`).

### Edit Sites (Blueprint Anchors)

Verified against: `420bea2707` (origin/dev); `/sdd-task` MUST re-run `grep -c` per row.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` | MODIFY | `    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx"]` | `models.py:172` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` | MODIFY | `    origin: Literal["deterministic", "llm", "community"]` | `models.py:242` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` | MODIFY | `class BookCard(BaseModel):` | `models.py:152` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | `_ADDED_COLUMNS: list[tuple[str, str]] = [` | `catalog.py:95` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | `_FTS_DDL = """` | `catalog.py:64` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | `    def _row_to_card(row: sqlite3.Row) -> BookCard:` | `catalog.py:286` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | `    def list_cards(self) -> list[BookCard]:` | `catalog.py:397` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    llm_dependent_tools: frozenset[str] = frozenset(` | `toolkit.py:265` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def _mutate(` | `toolkit.py:459` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    def get_tools(` | `toolkit.py:713` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def create_tree(` | `toolkit.py:745` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def delete_tree(self, tree_name: str) -> dict[str, Any]:` | `toolkit.py:781` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def rename_tree(` | `toolkit.py:800` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def tag_node(` | `toolkit.py:1958` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def add_node(` | `toolkit.py:2674` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | (same pattern for `vacuum_tree:1717`, `optimize:1541`, `index_segments:1456`, `insert_markdown:2014`, `insert_ebook:2093`, `insert_content:2169`, `import_file:2193`, `import_pdf:2212`, `import_folder:2552`, `delete_node:2643`, `update_node_content:2737`, `update_node:2770`) | `toolkit.py` | 1 each |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/pageindex.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex-library.yaml` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:` | `library.py:664` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    def get_toc(self, book_id: str) -> dict[str, Any]:` | `library.py:638` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    def list_books(self) -> list[BookCard]:` | `library.py:613` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def add_book(` | `library.py:1507` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def remove_book(self, book_id: str) -> bool:` | `library.py:1973` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def doctor(` | `library.py:474` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def relate_books(` | `library.py:1157` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    def _invalidate_graph(self, book_id: str) -> None:` | `library.py:1960` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `                adapter=self.adapter if self.adapter is not None else _NullAdapter(),` | `library.py:336` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/notebooks.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` | MODIFY | `    read_tools: frozenset[str] = frozenset(` | `toolkit.py:39` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` | MODIFY | `    description = (` | `mcp_server.py:93` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("add")` | `cli.py:103` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("list")` | `cli.py:248` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("relate")` | `cli.py:450` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("doctor")` | `cli.py:710` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("remove")` | `cli.py:778` | 1 |
| `.claude/skills/bookstore/SKILL.md` | MODIFY | `## Choose books, search sections, read evidence` | `SKILL.md` | 1 |
| `.agents/skills/bookstore/SKILL.md` | MODIFY | `## Choose books, search sections, read evidence` | `SKILL.md` | 1 |
| `wiki/knowledge/bookstore-notebooks.md` | CREATE | — | — | — |
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY | `## Gotchas` | `pageindex-local-mcp.md` | 1 |
| `wiki/knowledge/bookstore-graph.md` | MODIFY | `## Relation types and their determinism` | `bookstore-graph.md:19` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Dependency direction**: `bookstore → pageindex` only. `knowledge/pageindex/*` never imports
  `knowledge/bookstore/*`. The policy hook in M2 is generic; the policy lives in M3.
- **Facade shape**: mirror `BookstoreToolkit` (`bookstore/toolkit.py:30`): `AbstractToolkit`
  subclass, `tool_prefix = "pageindex"`, explicit `async def` per tool with the *same* name and
  parameters as `PageIndexToolkit` so `get_tools()` yields identical `pageindex_*` names. Keep
  `llm_dependent_tools` equal to `PageIndexToolkit.llm_dependent_tools` so the unchanged factory
  hides the same tools without `llm:`.
- **Lazy heavy imports + stdout purity**: the facade module must be importable under the factory's
  `redirect_stdout(stderr)`; follow `mcp_server.py`'s guard comments. No `print`.
- **Hook placement**: `_authorize_write` runs *before* `tree_lock` (`toolkit.py:771, 783, 832, …`)
  so a denied write never takes a lock or bumps a generation.
- **Catalog migration**: add `("kind", "kind TEXT NOT NULL DEFAULT 'book'")` and
  `("notes_for", "notes_for TEXT")` to `_ADDED_COLUMNS` (`catalog.py:95`); add `kind` to
  `_FTS_DDL` and the rebuild; `catalog_search` filters `kind='book'`.
- **Anchors are metadata, not schema**: written with `tag_node(metadata=...)` (shallow merge → write
  the whole `anchors` list each time); read through the tree store. Validate with `Anchor` on read;
  malformed anchors are reported by `doctor --notes`, never raised to an agent.
- **Generation-keyed cache**: `annotations_for` keys its per-notebook index on the tree's generation
  signature (FEAT-831 `get_generation`, `toolkit.py:896`) so MCP writes are seen on the next read.
- **Import copies through the stores**: tree JSON via `JSONTreeStore`, bodies via
  `NodeContentStore`, revisions via `SegmentStore.revision_path`; never `shutil.copytree` of a
  guessed layout. Hold the same locks as `add_book` (source lock by sha, book lock by slug).
- **Skill text** (both twins): step 1 becomes `bookstore_find_books`; add "Annotations returned next
  to a section are the reader's notes — cite them as *Notebook: <title>*, never as book pages."
- Google-style docstrings, strict typing, `self.logger`, 120 columns; tests next to the existing
  ones under `packages/ai-parrot/tests/knowledge/bookstore/` and `tests/mcp/`.

### Known Risks / Gotchas
- **A plain `pageindex` server pointed at `library/trees`** has no policy. Not denied (out of our
  control); `bookstore doctor` reports broken bindings (card → missing tree, tree → no card) and
  suggests `add --import` / `remove`. Document it as unsupported for writes.
- **Remap is best-effort.** Title matching after a re-index can mis-anchor when two sections share
  a title; prefer `(doc_id, title, nearest start_page)` and fall back to `stale`. Never delete.
- **Slug collisions on import** reuse `add_book`'s allocation (`taken_slugs`, `catalog.py:403`);
  `_notes` suffix must not collide with a real book slug ending in `_notes` — reject a *book* slug
  ending in `_notes` at allocation time.
- **Reserved names**: notebook names must pass `_is_reserved_tree_name` (`library.py:158`) and
  `_TREE_NAME_RE`; the lazy-registration sweep ignores `--staging-` / `REPLACED_MARKER` trees.
- **`read_section` is sync**: see M4 note; do not make `BookstoreToolkit.read_section`'s MCP
  contract depend on the choice.
- **Two processes, one `library.db`**: the facade only reads; WAL is on (`catalog.py:198`). The lazy
  upsert happens in Bookstore's process (CLI or `bookstore mcp`). If both servers run at once the
  registration simply happens on the read side.
- **`find_books` with no `bm25s`**: `PageIndexToolkit.search` cannot run BM25; degrade to a title
  substring match over sector nodes and say so in `hint`.
- **Cross-feature**: `pageindex/toolkit.py` is also touched by `pageindex-toolkit-fixes` and
  FEAT-849; `bookstore/library.py` by `bookstore-reindex-atomic-swap`. Land after them or rebase.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `bm25s` | already an `ai-parrot[bookstore]` extra | sector search without an LLM |

---

## Decisions

```yaml
schema_version: 1
document_id: bookstore-notebooks-shared-pageindex
entries:
  - id: book-trees-are-evidence-notebooks-are-separate-trees
    statement: A Bookstore book tree is never written by anything but Bookstore's own ingest; reader-authored notes, footnotes, relation sheets and classification live in separate PageIndex notebook trees (<book_id>_notes per book, _library_notes per scope) in the same library trees directory, registered lazily by naming convention and never rebuilt by re-index.
    relation: constrains
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "file:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py"]
    contradicts: []
    supersedes: []
    rationale: Annotations inside a book tree are lost on re-index and are cited as book evidence; separate trees survive re-index by construction and keep citations honest.
    rejected_alternatives: ["Annotate inside the book tree with re-index preservation", "SQLite annotation overlay outside PageIndex"]
  - id: pageindex-write-policy-hook-is-generic
    statement: PageIndexToolkit declares its mutating tools in write_tools, calls _authorize_write(tree_name, op) before taking any tree lock, and offers read_only; it carries no Bookstore knowledge — the library policy lives in parrot.knowledge.bookstore.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py"]
    contradicts: []
    supersedes: []
    rationale: Keeps the dependency direction bookstore → pageindex and makes read-only servers a one-flag feature.
    rejected_alternatives: ["Hand-listing write tools in the template exclude slot"]
  - id: library-served-by-bookstore-facade-over-both-scopes
    statement: PageIndex tools over the Bookstore library are exposed only through LibraryPageIndexToolkit, a Bookstore-owned facade served by the unchanged parrot mcp-local machinery from a second packaged template (pageindex-library), routing each tree to the project or global scope and never writing library.db; PageIndexToolkit stays single-storage_dir and the existing pageindex template is untouched.
    relation: constrains
    about: [knowledge-pageindex, tools]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "file:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py"]
    contradicts: []
    supersedes: []
    rationale: FEAT-842 (sdd/specs/pageindex-local-mcp-toolkit.spec.md, decision pageindex-served-by-packaged-template-only — not yet in the approvals ledger, so it cannot be linked here) rejected a user-level shared library for the plain pageindex server; this spec adds the Bookstore-scoped surface as a second template without changing that server, the runner, the seeder, the installer or the host adapters. The new module knowledge/bookstore/pageindex.py is created by M3; targets name existing files only.
    rejected_alternatives: ["Pointing the plain pageindex template at library/trees", "A multi-directory PageIndexToolkit", "One template per scope"]
  - id: sectors-are-the-authoritative-which-books-answer
    statement: find_books answers which books of the library treat a subject from the librarian's sector tree (_library_notes) first, returning the anchored ToC entries, and only falls back to catalog FTS when no sector matches; automatic communities are never the source of membership.
    relation: constrains
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "file:packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py"]
    contradicts: []
    supersedes: []
    rationale: Two-step retrieval (sector → books → index entries) without reading bodies is the funnel the user asked for; communities stay a suggestion for drafting.
    rejected_alternatives: ["Communities as membership source", "FTS first with sectors as a boost"]
```

## Decision Waivers

<!-- none -->

## Consequences

<!-- decision-audit: input_digest=sha256:cdc35cf9bc33fc89cd912a0bcd1265245f0f8323c9e13a8ed8a3c573e86b339a evaluation_digest=sha256:4492f02ce7478ef75964045fcbb367abcccca91de28dea8a8c6f5fda0720b55d rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: catalog, ingest, local-toolkits, notebooks
- Targets resolved: 5/5
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
    "targets_resolved": 5,
    "targets_total": 5,
    "unmapped_tags": [
      "catalog",
      "ingest",
      "local-toolkits",
      "notebooks"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:4492f02ce7478ef75964045fcbb367abcccca91de28dea8a8c6f5fda0720b55d",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:cdc35cf9bc33fc89cd912a0bcd1265245f0f8323c9e13a8ed8a3c573e86b339a",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:3cd253e439e42448186f344e00528b8a14c2086730eb57603f5b65fbb80a94ba",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] One notebook per book, one per library? — *Resolved in brainstorm*: both; book notebooks for footnotes/notes, the library notebook for Dewey-style sectors and relation sheets.
- [x] Are sectors authoritative for "which books treat X"? — *Resolved in brainstorm*: yes; two-step retrieval (sector → books → anchored ToC entries), FTS/communities as fallback only.
- [x] Who populates the classification? — *Resolved in brainstorm*: the human, the agent on the human's instruction via PageIndex tools, and Bookstore drafting proposals from ToCs and communities.
- [x] `add --import <path>` from outside the library: copy or move? — *Resolved in brainstorm*: copy, original untouched; `--move` can be added later.
- [x] Node-level writes on a book tree: fully denied, or `tag_node` allowed for OKF typing? — *Resolved in brainstorm*: fully denied; OKF typing happens at ingest, and a tag that must survive re-index belongs in the notebook.
- [x] Naming constraint — *Resolved in brainstorm*: tree names cannot contain dots (`content_store.py:41`), so `<slug>_notes` and `_library_notes`; never `--`.
- [x] `find_books` first in the skill funnel? — *Resolved in brainstorm*: always; it falls back to FTS and says so.
- [x] `--as book` on a tree with 0 or N documents — *Resolved in brainstorm*: exactly one document required; 0 → `--as notes` only; N → refused (split out of scope v1).
- [x] Which `rel` does a relation sheet project into? — *Resolved in brainstorm*: `metadata.rel` within the existing `RelationKind`, default `parallels`, first anchor = source for directed kinds; no new kind, no `REL_WEIGHTS` change.
- [x] Who catalogues a notebook created over the PageIndex MCP? — *Resolved in brainstorm*: naming convention on disk + lazy registration by Bookstore on its next read; the MCP toolkit only reads the catalog, never writes it.
- [x] Scopes — *Resolved in brainstorm*: one server serves both the project and the global library (a Bookstore-owned facade routing to the per-scope toolkits, not a multi-directory `PageIndexToolkit`; one `_library_notes` per scope, `find_books` merges project-first, anchors carry `scope`).
- [ ] Should `read_section` become `async` (cleanest for `annotations_for`) or keep its sync signature with a sync notebook read? Implementation call; the MCP tool contract is unchanged either way. — *Owner: implementer (M4 task)*
- [x] Q2 (design-research S5, escalated): the plain `pageindex` template pointed at `library/trees` bypasses the facade's policy. This spec only *documents* that as unsupported and lets `doctor` detect damage. Should v1 add a **generic storage-ownership marker** honoured by `PageIndexToolkit` itself (e.g. a `.owner` file in `storage_dir` that a toolkit constructed without the matching `owner=` refuses to write to — Bookstore-agnostic, so the dependency direction holds), or is "protection only through the new server" acceptable for v1? — *Owner: Jesus*: **Resolved 2026-11-11** — protection only through the new server for v1; no generic ownership marker. The plain-template setup stays documented as unsupported and `doctor` detects damage.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.167.0, reasoning high, 4 min 32 s) · Status: completed
> (the first attempt failed at brief rendering on a literal `{{repo_root}}` in the brainstorm text; the brief inputs were
> neutralised and the run repeated) · Transcript: `sdd/state/FEAT-876/design_research/`
> Every `affected_paths` entry passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Separate notebook catalog model, or every caller filters `kind='book'` (architecture) | CONFIRM (second half) / REJECT (separate table) | One table keeps `tree_name UNIQUE` and slug allocation as the collision guard; notebook rows fill the NOT NULL source columns with defined values, and every card-enumerating path filters `kind` | §2 Overview, §5 AC |
| S2 | Lazy registration leaves a window where `<book>_notes` is a free tree (risk) | CONFIRM | Verified: the facade reads the catalog for the deny decision; classification now uses name + catalog, independent of the row | §2 Overview, M3 `_resolve`, §4 test |
| S3 | Centralize authorization at `_mutate`, cover `index_segments`, add a completeness test (architecture) | CONFIRM | Verified `_mutate` at `toolkit.py:459` is the common boundary for node ops/apply; create/delete/rename/vacuum/index_segments lock directly | §2 Overview, M2 skeleton, §4 test |
| S4 | Authorize both endpoints of `rename_tree` (risk) | CONFIRM | Verified signature `(src, dst, *, overwrite)` at `toolkit.py:800` | §2 Overview, M3 skeleton, §4, §5 AC |
| S5 | Plain `pageindex` template can bypass the facade; add an ownership guard or narrow the claim (risk) | ESCALATE | True; the spec already narrows the claim (doctor detects), but a generic ownership marker is a product decision | §8 Q2 |
| S6 | Keep `list_trees` schema (`list[str]`), add a separate annotated listing (api) | CONFIRM | Verified `toolkit.py:741` returns `list[str]` | §2 Overview, M2/M3 skeletons, §5 AC |
| S7 | Test no-LLM filtering on the facade; `_NullAdapter` makes the default LLM walk fail (testing) | CONFIRM | Verified `_NullAdapter()` at `library.py:336`; `search` defaults `use_llm_walk=True` and only checks `is not None` (`toolkit.py:1768`); Bookstore's own `search_book` passes `has_llm` (`:661`) | §2 Overview, M3 skeleton, §4 test |
| S8 | Stage the import, validate, publish atomically, hash the logical snapshot (risk) | CONFIRM | Verified stores expose per-piece operations, no cross-store copy; `--staging-` marker and sweep already exist (`library.py:73`) | §2 Import, §4 tests, §5 AC |
| S9 | Collision-safe anchor remapping, not title alone (risk) | CONFIRM | Verified `SegmentStore.list_revisions` (`segment_store.py:106`) retains old revision files, so content matching is available | §2 Overview, M4 skeleton, §4 test |
| S10 | Preserve manual relations during re-index invalidation (risk) | CONFIRM | Verified `_invalidate_graph` (`library.py:1960`) calls `delete_relations(book_id=...)` with no origin filter (`:1969`) | §2 Overview, M4 skeleton, §4/§5 |
| S11 | `(scope, book_id)` identity at every read boundary (api) | CONFIRM | Verified project-first masking in `merged_cards` / `resolve_book`; anchors already carry `scope`, resolution now uses it | §2 Overview, §4 tests |
| S12 | Concurrency and generation-consistency tests for two-server use (testing) | CONFIRM | Reasonable given FEAT-831 protects single trees only | §4 Integration Tests |

Summary: **11** confirmed (S1 partially, its separate-table half rejected) · **0** rejected outright · **1** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/knowledge/bookstore-notebooks.md` — create: notebooks (per book / per library), anchors and `anchor_status`, sectors and the two-step `find_books`, drafting, relation sheets, `add --import`, the write policy table, the `pageindex-library` server, degraded modes.
  - `wiki/knowledge/pageindex-local-mcp.md` — update: `write_tools` / `read_only`, the `pageindex-library` template, "pointing the plain template at a library is unsupported for writes".
  - `wiki/knowledge/bookstore-graph.md` — update: `origin: "manual"` edges from relation sheets and the `relate --from-notes` command.
- **API modules**:
  - `parrot.knowledge.bookstore.library`, `parrot.knowledge.bookstore.pageindex`, `parrot.knowledge.bookstore.notebooks`, `parrot.knowledge.pageindex.toolkit`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-10 | Jesus Lara (with Claude) | Initial draft from the accepted brainstorm |
