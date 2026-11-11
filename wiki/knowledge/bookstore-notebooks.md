---
title: Bookstore notebooks
summary: Per-book and per-library notebooks over the Bookstore's PageIndex trees — anchors, sectors, find_books, relation sheets, tree import and the pageindex-library server.
---

# Bookstore notebooks

## Purpose

**The book is evidence, the notebook is yours.** A Bookstore book tree is the indexed text of a book and is
read-only. Everything a reader (human or agent) wants to add — reading notes, footnotes on a section, a
classification of the library, a claim that two books are related — goes into a **notebook**: an ordinary
PageIndex tree in the same `<library>/trees/` directory, catalogued with `kind="notes"`.

There are two kinds of notebook tree:

| Tree | Name | Holds | Use it for |
|---|---|---|---|
| Book notebook | `<book_id>_notes` (in the book's own scope) | Reading notes and virtual footnotes anchored at sections of one book | Annotating one book: what a chapter argues, where a passage matters |
| Library notebook | `_library_notes` (one per scope) | Librarian **sectors** (Dewey-like, `metadata.sector_code`) anchoring books and ToC entries, plus relation sheets | Classifying the library so `find_books` can answer "which books treat X, and where" |

Both are ordinary PageIndex trees: they are written with the normal `pageindex_*` tools (through the
`pageindex-library` server below) or by the Bookstore itself (`ensure_notebook`, drafting).

Catalog rows distinguish the two kinds of tree with the `kind` (`"book"` | `"notes"`) and `notes_for` columns of
`library.db`. Every read path that lists books (`list_books`, `catalog_search`, `search`, `related_books`,
`relate_books`, `communities`, `export_wiki`) only sees `kind="book"` rows, so notebooks never show up as books.

## Public API

- [`Bookstore`](ref:parrot.knowledge.bookstore.library.Bookstore) — the library facade:
  - `notebook_for(book_id)` — the book's `<book_id>_notes` card, or `None`. A conventional tree that exists on disk
    without a row is registered lazily (`kind="notes"`, `source_format="tree"`, `card_origin="fallback"`).
  - `library_notebook(scope)` — the scope's `_library_notes` card, or `None` (same lazy registration).
  - `ensure_notebook(book_id, scope="project")` — create the conventional tree when missing and register it;
    `book_id=None` targets the scope's library notebook. A book notebook always lives in the book's own scope.
  - `annotations_for(book_id, node_id)` — the notes anchored at one section, as `Annotation` models.
  - `remap_anchors(book_id, previous=None)` — re-point anchors after a re-index; returns
    `{"current", "remapped", "stale"}` counts. Never deletes a note.
  - `find_books(query, top_k=5)` — sectors first, catalog FTS fallback (see below).
  - `import_tree(source, scope="project", *, as_kind="book", notes_for=None, title=None, force=False)` — adopt an
    existing PageIndex tree; returns `(card, status)` with status `added` | `adopted` | `skipped`.
  - `remove_book(book_id, *, with_notes=False)` and `doctor(..., notes=True)` — notebook-aware lifecycle.
- [`notebooks`](ref:parrot.knowledge.bookstore.notebooks) — drafting and relation sheets:
  `draft_library_notebook(store, scope="project", *, use_llm=True)`, `draft_book_notebook(store, book_id)`,
  `relation_sheets(store, scope=None)`, `apply_relation_sheets(store, scope=None)`.
- [`LibraryPageIndexToolkit`](ref:parrot.knowledge.bookstore.pageindex.LibraryPageIndexToolkit) — the
  `pageindex_*` tool surface over the project and global libraries, with the write policy below.
- Models in `parrot.knowledge.bookstore.models`: `Anchor` (`book_id`, `scope`, `node_id`, `doc_id`, `revision`),
  `Annotation` (`note_tree`, `node_id`, `title`, `body`, `note_kind`, `origin`, `anchor_status`) and `SectorDraft`.

The `bookstore` MCP server and `BookstoreToolkit` expose the reads: `bookstore_find_books` (step 1 of the research
funnel), `bookstore_read_section` (now with `annotations: [...]`) and `bookstore_get_toc` (each entry carries
`has_notes`). Both fields are empty/false when the book has no notebook, so existing callers see no change.

## Write policy

| Target tree | Structural ops | Node ops |
|---|---|---|
| catalogued `kind=book` | denied | denied |
| catalogued `kind=notes` | `rename_tree` / `delete_tree` denied; the rest allowed | allowed |
| not in the catalog | allowed | allowed |

Structural ops are `create_tree`, `delete_tree`, `rename_tree`, `insert_*`, `import_*`, `vacuum_tree`,
`optimize` (with `apply=True`) and `index_segments`; node ops are `add_node`, `update_node`,
`update_node_content`, `delete_node` and `tag_node`. A refused call raises `PageIndexWriteDenied`; a denied write to
a book names the notebook to use instead (`Write notes in '<book_id>_notes' instead.`).

A tree is classified **by name and catalog together**: `_library_notes`, or `<X>_notes` where `X` is a catalogued
book, is a notebook from the moment it exists — before Bookstore lazily registers its row — so the registration gap
cannot be used to rename or delete it. Reserved Bookstore tree names (in-flight staging trees) are refused for every
write. `rename_tree` authorizes both `src` and `dst`, and both trees must be in the same library scope.

## Configuration & Parameters

### Anchors and `anchor_status`

A note points into a book through `metadata.anchors`, a list of `Anchor` dicts written with
`pageindex_tag_node(metadata=...)` or `pageindex_add_node(metadata=...)`:

```json
{"note_kind": "note", "anchors": [{"book_id": "meditations", "scope": "project", "node_id": "0007",
  "doc_id": "…", "revision": "…"}]}
```

- An anchor **without** `node_id` points at the whole book (sectors use these); one with `node_id` points at a section.
- `note_kind` is one of `footnote`, `note`, `sector`, `sheet`; `origin` is `human` (default), `agent` or `draft`.
- Identity is `(scope, book_id)`: an anchor into another scope is ignored for annotated reads, so a project book and
  a global book with the same id never share notes.
- After a re-index (`bookstore add` returning `updated`) the Bookstore snapshots the old tree and runs
  `remap_anchors`. An anchor whose revision is still live stays `current`; otherwise the old section is matched in
  the new tree by text fingerprint (then title, then nearest page) and re-pointed (`remapped`), or kept unchanged as
  `stale` when no unique match exists. The worst status of a note's anchors is stored in `metadata.anchor_status`
  and returned on every `Annotation`.

### Sectors and the two-step `find_books`

Sectors are nodes of `_library_notes` with `metadata.sector_code` (a 3-digit Dewey-like code such as `"170"`) and
anchors to books and ToC entries. `find_books(query)`:

1. searches every scope's library notebook (project first) with PageIndex hybrid search — BM25, plus the LLM walk only
   when a model is configured. A hit counts only when it is a sector sharing at least one query term with its code,
   title, summary or body;
2. resolves the sector's anchors against the catalog: whole-book anchors name the book, node anchors become ToC
   `entries` (`node_id`, `title`, `start_page`, `end_page`). Book bodies are never read.

It returns `{"source": "sectors", "sectors": [{code, title, books: [{book_id, title, scope, entries}]}]}`. When no
sector matches it falls back to `{"source": "catalog_fts", "books": [...], "hint": ...}` — the same lexical search as
`bookstore_catalog_search`, with a hint to run `bookstore notebook draft --library`.

### Drafting

Drafts propose structure as ordinary notebook nodes stamped `metadata.origin="draft"`. A re-run updates its own
drafts and **never** overwrites a node of any other origin (counted as `skipped_human`).

- `bookstore notebook draft --library [--global] [--no-llm]` — one sector per book community (run
  `bookstore relate --all` first so communities exist). With a model, each community gets one structured LLM call
  for its code and title (falling back to the no-LLM sector on any failure or malformed reply); without one, codes
  are sequential (`000`, `010`, …) and titles are the community labels.
- `bookstore notebook draft --book <book_id>` — a reading-guide skeleton: one empty `note` per top-level ToC entry,
  anchored with `book_id`, `scope`, `node_id`, `doc_id` and `revision`.

Both print `created / updated / skipped (human)` counts (`--json` for the dict).

### Relation sheets

A relation sheet is any notebook node (in `_library_notes` or a `<book_id>_notes`) whose anchors point at **two or
more distinct catalogued books**. Sectors are classification, not relation claims, and are never projected. The
sheet's `metadata.rel` picks the relation kind (default `parallels`; an unknown kind skips the node with a warning).
Directed kinds (`influenced_by`, `responds_to`) take the first anchored book as the source of one edge per other
book; symmetric kinds emit one edge per pair. The sheet body (first 500 characters) becomes the edge rationale.

`bookstore relate --from-notes` writes the sheets as `origin="manual"` edges — alone, or before the normal stages
when combined with `--all` / `BOOK_ID`s. See [Bookstore graph](bookstore-graph.md) for how manual edges survive.

### `bookstore add --import`

`bookstore add FILE --import [--as book|notes] [--for BOOK_ID] [--title …] [--force] [--global]` adopts an existing
PageIndex tree without re-ingesting it. `FILE` is a tree `.json` path outside the library (copied; the original is
untouched) or an uncatalogued tree name inside it (adopted in place).

- `--as book` (default) requires exactly one document in the tree; a name ending in `_notes` must be imported with
  `--as notes`.
- `--as notes --for BOOK_ID` lands the tree as `<BOOK_ID>_notes`; `--as notes` alone lands it as `_library_notes`.
  An existing notebook is replaced only with `--force`, and the old one is kept as `<name>_<UTC timestamp>`.
- Every body and segment reference must resolve, otherwise the import fails.
- The same snapshot (same sha256) imported again prints `skipped`.
- `--author`, `--topic` and `--relate` cannot be combined with `--import`.

### Other CLI switches

| Command | Effect |
|---|---|
| `bookstore list --notes [--json]` | List notebooks (`tree_name`, `scope`, `notes_for`) instead of books |
| `bookstore remove BOOK_ID --with-notes` | Also delete the book's notebook; without it the notebook is kept as an orphan (`notes_for` cleared) |
| `bookstore doctor --notes` | Also report, per scope, notebooks, orphans, malformed anchors, stale anchors and broken bindings (card without tree, tree without card) |

### The `pageindex-library` server

`LibraryPageIndexToolkit` serves the full `pageindex_*` tool surface (same names and parameters as
`PageIndexToolkit`) over both library scopes. Each call is routed to the scope that owns the target tree (project
first) and checked against the write policy above. The facade reads the catalog but never writes `library.db`.
Additions over plain PageIndex: `pageindex_create_tree` takes `scope` (`project` default, or `global`), and
`pageindex_list_library_trees` returns `[{tree_name, scope, kind}]` with `kind` in `book` / `notes` / `free`.

```yaml
toolkits:
  pageindex-library:
    class: parrot.knowledge.bookstore.pageindex.LibraryPageIndexToolkit
    kwargs:
      project_root: <repo>
      max_result_chars: 24000
    # llm: anthropic:claude-haiku-5-5
    exclude: [pageindex_agentic_retrieve]
    env: {}
```

Install it with `parrot toolkits install pageindex-library`. `project_root` resolves the project library; the
global library comes from `PARROT_LIBRARY_DIR` / `PARROT_HOME` as usual.

## Usage Examples

```bash
bookstore relate --all                          # communities are the input of library drafting
bookstore notebook draft --library --no-llm     # sectors 000, 010, … into _library_notes
bookstore notebook draft --book meditations     # reading-guide skeleton in meditations_notes
bookstore add ./old-notes.json --import --as notes --for meditations
bookstore relate --from-notes                   # relation sheets → manual edges
bookstore doctor --notes
```

An agent annotating a book through `pageindex-library`:

1. `pageindex_create_tree(tree_name="meditations_notes")` — a book notebook (writing to `meditations` is denied)
2. `pageindex_add_node(tree_name="meditations_notes", title="On the inner citadel", body="…",
   metadata={"note_kind": "footnote", "anchors": [{"book_id": "meditations", "node_id": "0007"}]})`
3. `bookstore_read_section("meditations", "0007")` now returns that note under `annotations`.

## Gotchas

- **Cite notes as notes.** Annotations returned next to a section are the reader's notes — cite them as
  *Notebook: <title>*, never as book pages. The skill copies carry this rule.
- **Pointing the plain `pageindex` template at a library is unsupported for writes** — use `pageindex-library`. A
  plain `PageIndexToolkit` whose `storage_dir` is `<library>/trees` bypasses the write policy entirely; for v1 the
  only protection is the `pageindex-library` server, and `bookstore doctor` detects the damage.
- **Notebooks are not books.** `catalog_search` and `list_books` never return them; use `bookstore list --notes`.
- **Removing a book keeps its notebook** as an orphan unless you pass `--with-notes`; `doctor --notes` lists orphans.
- **Drafts need communities.** `notebook draft --library` drafts one sector per community; with no communities
  (fewer than 3 books, or no `relate --all` yet) it drafts nothing.
- **Remapping never deletes.** A `stale` anchor stays in place for a human to fix; `doctor --notes` counts them.

### Degraded modes

- **No LLM.** `find_books` and the `pageindex-library` `search`/`retrieve` are BM25-only; `notebook draft --library`
  maps communities 1:1 to sequential sector codes with the community labels as titles. Book drafting never uses a model.
- **No `bm25s`.** `find_books` matches sectors by title only and returns a `hint` saying so (install
  `ai-parrot[bookstore]`); the catalog fallback still works, because it is SQLite FTS5.

## Related

- [Bookstore graph](bookstore-graph.md) — relations, communities and `origin="manual"` edges
- [Bookstore agentic retrieval](bookstore-agentic-retrieval.md) — validated citations over books
- [Bookstore for Codex](bookstore-codex.md) — installer and session guide
- [PageIndex Local MCP Toolkit](pageindex-local-mcp.md) — the plain `pageindex` server, `write_tools` / `read_only`
