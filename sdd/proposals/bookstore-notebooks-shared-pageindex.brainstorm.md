---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [bookstore, pageindex, mcp, local-toolkits, notebooks, catalog, ingest]
---

# Brainstorm: Bookstore Notebooks over a Shared PageIndex Store

**Date**: 2026-11-10
**Author**: Jesus Lara (with Claude)
**Status**: accepted
**Recommended Option**: A

---

## Problem Statement

Bookstore is built **on top of** PageIndex: `Bookstore` composes one
`PageIndexToolkit` per library scope whose `storage_dir` is
`<library>/trees/` (`knowledge/bookstore/library.py:1-11, 250-260`;
`knowledge/bookstore/config.py` `LibraryLocation.trees_dir`). Every
`bookstore add` ends in `toolkit.create_tree(...)` and the book lives in
PageIndex's native layout. The catalog (`library.db`) is a metadata layer
over those trees — fichas, FTS5, sha256 identity, relations, communities —
not a second content index.

PageIndex has no global index of its own. Every consumer instantiates its
own toolkit over its own directory: the wiki runtime over
`<wiki>/pageindex`, Studio over `<storage>/pageindex`, and the FEAT-842
local MCP server (`parrot mcp-local pageindex`) over
`<repo>/.parrot/pageindex` (`mcp/_toolkit_templates/pageindex.yaml`). The
FEAT-842 spec explicitly decided "the Bookstore server stays separate" and
"no user-level or shared library; storage is per repository".

That decision leaves three things a user of both planes runs into today
(observed in the `parrot-bookstore` test repository, where the PageIndex
MCP had to be pointed by hand at `.parrot/library/trees`):

1. **Reading the library through PageIndex is possible but unguarded.**
   Pointing the PageIndex MCP at `library/trees` works for reads (FEAT-831
   per-tree `flock` + generation-signature reload make two writers safe at
   the file level), but the server also exposes every structural write —
   `create_tree`, `delete_tree`, `rename_tree`, `import_*`, `insert_*`,
   `vacuum_tree`, `optimize --apply` — on trees the catalog believes it
   owns. One `rename_tree` leaves a card with a dangling `tree_name`; the
   (now closed) ledger issues `d77afc39e913` / `d2289b11be8c` show how
   brittle that coupling already is. The only defence is hand-listing tools in the
   template's `exclude:`, and because the server serves "whatever
   `get_tools()` returns", every new tool reopens the hole.

2. **Annotations have nowhere safe to live.** The user wants to use the
   PageIndex *write* tools over ingested books to build richer knowledge:
   virtual footnotes on sections, reading notes, cross-book relation
   sheets, and a Dewey-style classification of the library. Writing those
   into the book's own tree is lost on the next re-index (`add_book` with
   status `"updated"` rebuilds the tree from the source — the same class of
   loss as `issue:9013034b010f` for hand-edited cards), and it blurs
   evidence with interpretation: the `bookstore` research skill tells the
   agent to "distinguish statements in the books from your interpretation",
   yet a note inside the book tree would be cited as *Book, "Section",
   pp. x–y*.

3. **A tree built elsewhere cannot become a book.** There is no way to
   register an existing PageIndex tree (from `.parrot/pageindex`, from a
   free-hand tree an agent created, from another repository) in the
   catalog without re-ingesting its source — and a notebook has no source
   to re-ingest.

**Users**: the human curating the library with the `bookstore` CLI and the
PageIndex MCP write tools; the research agent (Claude Code / Codex via the
`bookstore` MCP and skill) that must answer "which books of this library
treat X, and where?" in two steps without reading the books.

## Constraints & Requirements

- **The book is evidence; the notebook is interpretation.** A book tree is
  immutable from the outside and re-indexable from its source. Notes,
  footnotes, relation sheets and classification live in separate trees
  that re-index never touches.
- **One storage directory per scope.** Notebooks are ordinary PageIndex
  trees inside the same `<library>/trees/` so one `PageIndexToolkit` (the
  Bookstore-internal one or an MCP server) sees books and notebooks alike.
  No second directory to point anything at.
- **Dependency direction stays `bookstore → pageindex`.** PageIndex must
  not import Bookstore. Whatever enforces the catalog's write policy lives
  in `parrot.knowledge.bookstore`, with at most a generic, policy-free hook
  in `PageIndexToolkit`.
- **No change to the generic MCP machinery.** `mcp/toolkit_server.py`,
  `toolkit_seed.py`, `toolkit_install.py` and `hosts.py` stay as they are
  (FEAT-842 non-goal, still binding). A new template file is allowed.
- **No-LLM mode keeps working.** Writing notes, anchoring footnotes, the
  two-step sector retrieval and `add --import` are deterministic. Only the
  *drafting* of a classification uses a model, and it degrades to the
  existing deterministic communities when none is configured.
- **Bookstore MCP stays read-only** (FEAT-533 §4, "no write tool over
  MCP"). Writes go through the PageIndex MCP over the library; Bookstore's
  MCP only gains read tools that understand notebooks.
- **The Dewey sectors are authoritative.** When a sector answers "which
  books treat X", that answer comes first and is labelled as the
  librarian's classification; FTS over cards and the automatic Leiden
  communities remain as fallback/suggestion, never as the source of
  membership.
- **Stdout purity** of both stdio servers is unchanged.

---

## Options Explored

### Option A: Notebooks as catalogued PageIndex trees + Bookstore-owned write policy

Two kinds of tree share `<library>/trees/`, distinguished by a new catalog
column `kind` (`book` | `notes`):

- **Book notebook** — one per book, `<slug>_notes` (tree names must match
  `^[A-Za-z0-9_-]{1,128}$`, `content_store.py:41`, so no dots; a single
  `_` also avoids the reserved `--staging-` marker, `library.py:73`),
  created empty on first write (or at ingest). Nodes are reading notes and *virtual
  footnotes*: a footnote is a notebook node whose metadata (set with the
  existing `tag_node(metadata=...)`) carries one or more **anchors**
  `{book_id, node_id, doc_id, revision}` into the book tree.
- **Library notebook** — one per scope, `_library_notes`. Its nodes are
  **sectors** in a Dewey-like hierarchy (`100 Philosophy › 170 Ethics ›
  171 Ethical theories`). A sector node anchors the *books* that belong to
  it **and the ToC entries** where each book treats the subject
  (`{book_id, node_id}`). Relation sheets between books live here too and
  may be projected into the existing relation graph with a new
  `origin: "manual"`.

Writes are governed by a **`LibraryPageIndexToolkit(AbstractToolkit)`**
in `parrot.knowledge.bookstore`: a *facade over `Bookstore`* that serves
the same tool surface and names as `PageIndexToolkit` (`tool_prefix =
"pageindex"`) and routes every call to the per-scope toolkit Bookstore
already holds (`Bookstore._toolkit(scope)`), so **one MCP server serves
the project and the global library** (resolved with `resolve_locations`,
exactly as the Bookstore MCP does). A tree is routed by the catalog (books
and registered notebooks carry a scope); an uncatalogued name resolves
project-first, then global; `create_tree` takes an optional `scope`
(default `project`); `list_trees` merges both scopes and annotates each
entry. Before dispatching, the facade enforces, per call:

| Target tree | Structural ops (`delete_tree`, `rename_tree`, `insert_*`, `import_*`, `vacuum_tree`, `optimize --apply`) | Node ops (`add_node`, `update_node*`, `delete_node`, `tag_node`) |
|---|---|---|
| catalogued `kind=book` | **denied** | **denied** (books are evidence) |
| catalogued `kind=notes` | `rename_tree` / `delete_tree` **denied** (use `bookstore remove` / `--import --force`); the rest allowed | allowed |
| not in the catalog | allowed | allowed |

`PageIndexToolkit` gains only a generic hook — a class-level
`write_tools: frozenset[str]` (sibling of `llm_dependent_tools`) and an
`_authorize_write(tree_name, op)` method that defaults to allow — so any
subclass or facade can refuse with a clear error and so a `read_only=True`
constructor flag can hide/refuse every write tool uniformly. PageIndex
stays single-`storage_dir`; the multi-scope routing lives in the Bookstore
facade (my call: a facade over the per-scope toolkits Bookstore already
owns is far smaller than teaching `PageIndexToolkit` several directories,
and keeps the dependency direction). A second packaged template,
`pageindex-library.yaml`, points `class:` at the facade; it needs no
`storage_dir` (locations are resolved from the server's working
directory, `{{repo_root}}` passed as `project_root` for determinism).

**Notebook registration is lazy, by naming convention.** A tree named
`<slug>_notes` (where `<slug>` is a catalogued book) or `_library_notes`
*is* a notebook the moment it exists on disk; Bookstore registers the
`kind=notes` row the first time it reads it (`notebook_for`,
`library_notebook`, `annotations_for`, `find_books`, `list --notes`,
`doctor`). The facade never writes `library.db`; it only reads it for the
deny decision. A row whose tree vanished is reported by `doctor`, not
deleted silently.

Bookstore reads become notebook-aware: `read_section` returns the
section **plus** `annotations: [...]` anchored to that node;
`get_toc` marks entries that have footnotes; a new read tool
`find_books(query)` implements the two-step retrieval over sectors.
`bookstore add --import <tree>` adopts an existing tree as a book or as a
notebook (see Feature Description). Re-index never rebuilds a notebook;
after a book is `"updated"`, anchors are remapped by `(doc_id, section
title)` and the rest flagged `stale_anchor` rather than dropped.

✅ **Pros:**
- Notebooks survive re-index by construction (never rebuilt).
- Evidence/interpretation separation is structural: a citation of a
  footnote names the notebook, never the book's pages.
- Zero new storage: the same `trees/` dir, the same PageIndex tools the
  user already wants to use, the same locks and generation reload.
- Write policy lives in Bookstore, next to the catalog it protects; the
  PageIndex hook is generic and reusable (`read_only` is a free by-product).
- `--import` and notebooks are the same mechanism: a free tree created via
  the MCP is exactly what `--import` adopts.

❌ **Cons:**
- Catalog schema migration (`kind`, `notes_for`) and a second template to
  maintain.
- Anchors are soft references; remapping after re-index is best-effort.
- Two servers (`parrot-bookstore` read, `parrot-pageindex-library` write)
  for one library — by design, but the operator has to install both.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `bm25s` | sector search without an LLM (already a Bookstore extra) | present via `ai-parrot[bookstore]` |

🔗 **Existing Code to Reuse:**
- `knowledge/pageindex/toolkit.py` — `tag_node(metadata=...)` for anchors; `llm_dependent_tools` pattern for `write_tools`.
- `knowledge/bookstore/library.py` — `_toolkit()`, `add_book()`, `read_section()`, `_draft_card()`, `optimize_book()`.
- `knowledge/bookstore/catalog.py` — `books` DDL + FTS; `upsert_relations`.
- `knowledge/bookstore/relations.py` — `origin` field on `BookRelation`; `detect_communities` as the no-LLM drafting source.
- `mcp/_toolkit_templates/pageindex.yaml` — template shape; `toolkit_server.py:325-374` include/exclude/llm-dependent filtering (unchanged).

---

### Option B: Annotate inside the book tree, teach re-index to preserve foreign nodes

Notes and footnotes are added as nodes **inside** the book's own tree
under a reserved `_annotations` branch, and sectors are tags on book
nodes. `add_book` on `"updated"` learns to carry the reserved branch and
tags over to the rebuilt tree.

✅ **Pros:**
- No new trees, no `kind` column; `agentic_retrieve` sees notes without any merge step.

❌ **Cons:**
- Re-index preservation is a merge problem (node ids change, sections move); it is the exact fragility `issue:9013034b010f` describes, now for content.
- Citations cannot distinguish the book from the reader; the research skill's evidence rule breaks.
- The library-wide classification has no natural home (a book tree is per book).
- Still needs the write policy to stop `delete_tree`/`rename_tree`, so Option A's hook is required anyway.

📊 **Effort:** Medium (higher risk)

🔗 **Existing Code to Reuse:** as A, plus the FEAT-840 segment revisions for node remapping.

---

### Option C: Annotation overlay in the catalog (SQLite), not in PageIndex

A new `annotations` table keyed by `(book_id, node_id, revision)` with
Markdown bodies; sectors as a `sectors` table; new `bookstore annotate` /
`bookstore classify` CLI commands.

✅ **Pros:**
- Simplest write policy: PageIndex stays read-only over the library, period.
- Transactional with the catalog.

❌ **Cons:**
- Not what the user asked for: notes are not PageIndex trees, so none of the PageIndex tools (search, outline, retrieve, OKF, optimizer, export) apply to them; no hierarchy for sectors beyond what we re-implement.
- Yet another ad-hoc store next to `library.db`; relation sheets as rows lose their prose.
- Bookstore MCP would need write tools, contradicting FEAT-533.

📊 **Effort:** Medium

---

## Recommendation

**Option A** is recommended because it is the only one that keeps all
four properties the conversation settled on at once: notebooks are
PageIndex trees (so every PageIndex tool applies), they survive re-index
by construction, evidence and interpretation are separated at the tree
level (so citations stay honest), and the write policy sits in Bookstore
next to the catalog it protects without PageIndex learning about
Bookstore. Option B trades a merge problem we already know is fragile for
a slightly simpler read path; Option C solves the policy problem by
abandoning the requirement.

---

## Feature Description

### User-Facing Behavior

**Setup.** `parrot toolkits install pageindex-library` seeds a section
whose class is the Bookstore facade and registers
`parrot-pageindex-library` in the detected hosts. One server serves the
project library (`<repo>/.parrot/library`) **and** the global one
(`~/.parrot/library`), the same two locations the Bookstore MCP reads.
`parrot-bookstore` stays as it is (read). Pointing the plain `pageindex`
template at a `trees/` directory remains possible but is documented as
unsupported for writes.

**Writing notes.** Through `parrot-pageindex-library` the agent (on the
human's instruction) or the human (in process) does, with existing tools:

```
pageindex_create_tree("kant-critica_notes")            # or Bookstore creates it lazily
pageindex_add_node("kant-critica_notes", title="On the antinomies", body=...)
pageindex_tag_node("kant-critica_notes", node_id, metadata={
    "anchors": [{"book_id": "kant-critica", "scope": "project", "node_id": "n14", "doc_id": "...", "revision": "..."}],
    "note_kind": "footnote"})
```

A structural or node write aimed at a catalogued book tree fails fast:
`PageIndexWriteDenied: 'kant-critica' is a Bookstore book (evidence);
write to 'kant-critica_notes' instead`.

**Reading with notes.** `bookstore_read_section(book_id, node_id)` returns
the section as today plus `annotations: [{note_tree, node_id, title,
body, note_kind, anchor_status}]`. `bookstore_get_toc` marks entries that
carry footnotes. Both are empty lists when there is no notebook, so
existing callers see no change.

**Classifying the library.** The library notebook `_library_notes` (one
per scope) is a sector tree. The human writes it, or asks the agent to write it with the
PageIndex tools, or runs `bookstore notebook draft --library` to have
Bookstore propose one from the cards, the ToCs and the existing
communities (LLM when `PARROT_BOOKSTORE_LLM` is set; otherwise one
sector per Leiden community with its label). A draft is written as a
normal notebook tree with `metadata.origin = "draft"` on every node the
human has not touched; `bookstore notebook draft --book <id>` does the
same for a book notebook (reading-guide skeleton from the ToC).

**Two-step retrieval.** `bookstore_find_books(query, top_k=5)`:

1. search the sector trees of every scope (BM25 over sector titles/bodies,
   LLM walk when configured), merged project-first → matching sectors,
   each with its anchored books;
2. for each book, the ToC entries the sector anchors (`node_id`, title,
   pages) → the agent goes straight to `read_section`.

The result carries `source: "sectors"`. When no sector matches, the tool
falls back to today's `catalog_search` and labels the result
`source: "catalog_fts"`; `communities` are surfaced as
`source: "community"` only on explicit request. The `bookstore` skill is
updated to start with `find_books`.

**Relation sheets.** A node in `_library_notes` (or in a book notebook)
that anchors two or more books is a relation sheet. `bookstore relate
--from-notes` projects such sheets into `book_relations` with
`origin: "manual"`, `rationale` = the node body, so `related_books` and
community detection see them; manual edges are never overwritten by the
LLM stage. The sheet's `metadata.rel` names the kind, restricted to the
existing `RelationKind` literal (`models.py:53-80`); when absent it
defaults to the symmetric `parallels`. For directed kinds
(`responds_to`, `influenced_by`) the first anchor is the source and each
further anchor a destination. No new kind and no change to `REL_WEIGHTS`:
manual edges weigh like their kind, `weight = 1.0` (my call).

**Importing a tree.** `bookstore add --import <tree-name|path> [--scope]
[--as book|notes] [--for <book_id>]`:

- `<path>` outside the library (e.g. `.parrot/pageindex/docs.json`): the
  tree file, its sidecar body directory and its `segments/` revisions are
  **copied** into `<library>/trees/` under a Bookstore-allocated slug; the
  original is left untouched (my call — see Open Questions).
- `<tree-name>` already inside `<library>/trees/` but uncatalogued (a
  free tree created via the MCP): adopted **in place**, no copy.
- `--as book` (default): a card is drafted from the tree
  (`_draft_card` path; LLM or fallback) with `source_format: "tree"`,
  `source_path` = origin path, `source_sha256` = sha256 of the tree JSON.
  Re-index of an imported book is `--import` again from the same origin.
  **A book tree holds exactly one document** (`Bookstore._document_of`,
  `library.py:~687`, takes `documents[0]` and raises on none; page reads,
  segments, agentic retrieval and citation labels all assume it). So
  `--as book` requires a tree with exactly one FEAT-840 document; a
  multi-document tree (what `import_folder` produces) is refused with
  `hint: one book per document — import each source file with bookstore
  add, or adopt the tree with --as notes`; a tree with no document (a
  free-hand `add_node` tree) can only be adopted `--as notes`. Splitting
  a multi-document tree into N books is out of scope for v1 (my call).
- `--as notes --for <book_id>`: catalogued as that book's notebook (one
  per book; refuses if one exists unless `--force`, which merges nothing
  and renames the old one to `<slug>_notes_<ts>`); `--as notes` without
  `--for` is the library notebook.

**Removing.** `bookstore remove <book_id>` removes the book and, by
default, keeps its notebook (re-catalogued as orphan notes, `notes_for
= NULL`, listed by `bookstore list --notes`); `--with-notes` removes both.

### Internal Behavior

- **Catalog**: `books` gains `kind TEXT NOT NULL DEFAULT 'book'` and
  `notes_for TEXT NULL` (book_id); `source_format` accepts `"tree"`;
  `card_origin` unchanged. `list_cards()` defaults to `kind='book'`;
  notebooks are reachable through `notebook_for(book_id)` /
  `library_notebook()`. FTS indexes notebooks' titles/summaries under a
  separate `kind` column so `catalog_search` can exclude them by default.
- **Write policy**: `PageIndexToolkit.write_tools` (class attribute, names
  with prefix) + `_authorize_write(self, tree_name, op) -> None`
  (default no-op) called at the top of every write tool. `read_only=True`
  makes `_authorize_write` raise and hides `write_tools` from
  `get_tools()` (`AbstractToolkit.exclude_tools` can back the hiding).
  `LibraryPageIndexToolkit` is a facade: it owns a `Bookstore`
  (`resolve_locations(project_root)`), exposes one delegating method per
  PageIndex tool (same names, so `get_tools()` yields the `pageindex_*`
  surface; whether written explicitly or generated is left to the
  builder, but the served names must equal `PageIndexToolkit.get_tools()`
  minus nothing), resolves `(scope, toolkit)` for the target tree through
  the catalog (project-first for uncatalogued names), applies the policy
  table, then delegates to `Bookstore._toolkit(scope)`. `Bookstore`
  itself keeps using plain `PageIndexToolkit`s (it *is* the owner).
- **Scopes**: anchors carry `scope`; a notebook in either scope may anchor
  a book of either scope. `_library_notes` exists per scope. `find_books`
  and `annotations_for` consult both. Collisions follow the catalog rule:
  project wins.
- **Anchors**: stored in notebook node metadata via `tag_node`; the
  `revision` comes from the book node's `doc_id`/`revision` (FEAT-840,
  `PageIndexNode.doc_id`/`.revision`, `schemas.py:129-130`; `doc_id` is a
  deterministic slug of the source name, `revision` a content hash, so
  "same `doc_id`, new `revision`" is a sound re-index signal). `Bookstore.annotations_for(book_id,
  node_id)` scans the notebook's nodes once per generation (cached by the
  tree's generation signature) and reports `anchor_status`: `current`,
  `remapped` (same `doc_id`, revision changed, section title matched) or
  `stale` (no match). Remapping runs after `add_book` returns
  `"updated"`.
- **Sectors**: sector nodes are ordinary notebook nodes with
  `metadata.sector_code` (e.g. `"171"`) and `metadata.anchors`
  (book-level anchors have no `node_id`; ToC anchors do).
  `find_books` searches the sector tree with the toolkit's `search`
  (BM25 / LLM walk) and resolves anchors against the catalog; it never
  reads book bodies.
- **Drafting**: `notebook draft --library` builds sector candidates from
  `BookCard.topics/genre/traditions`, community labels and ToC titles;
  with an LLM, a `SectorDraft` Pydantic model (code, title, rationale,
  book anchors with ToC node ids) is requested per community; without
  one, communities map 1:1 to sectors. Existing human-edited nodes
  (`origin != "draft"`) are never overwritten.
- **Import**: copies via `NodeContentStore` + `SegmentStore` paths (never
  hand-built globbing), under the same source/book operation locks as
  `add_book`, then publishes through the FEAT-831 generation path so a
  concurrent reader sees an atomic appearance.
- **Re-index**: `add_book` `"updated"` path is unchanged for the book
  tree; a post-step calls `remap_anchors(book_id)`.

### Edge Cases & Error Handling

- `book_id == tree_name` is an invariant (`models.py:155`; on
  `"updated"` the slug is `existing.book_id`), so `notes_for` is both the
  book id and the book's tree name; a re-index never renames a book.
- A write through the plain `pageindex` template over the library: not
  denied (no policy) but `bookstore doctor` reports trees whose catalog
  binding is broken (card → missing tree, tree → no card) and offers
  `--import` / `remove` as repairs.
- `--import` of a tree whose `tree_name` collides with an existing slug:
  Bookstore allocates `<slug>-2` as `add_book` already does for titles.
- `--import` of a `.notes` tree without `--as notes`: refused with a hint.
- Sector tree missing: `find_books` returns `source: "catalog_fts"`
  immediately and `hint: "no library notebook — run bookstore notebook
  draft --library"`.
- Anchor to a `node_id` that no longer exists after remap: `stale`,
  never dropped; `bookstore doctor --notes` lists them.
- Two writers: notebook writes go through the same per-tree `flock`;
  `annotations_for` reloads on generation change, so a note added over
  MCP is visible to the Bookstore MCP's next `read_section`.

---

## Capabilities

### New Capabilities
- `bookstore-notebooks`: per-book and per-library notebook trees, anchors, annotated reads, sector-driven two-step retrieval, drafting.
- `pageindex-write-policy`: `write_tools` / `_authorize_write` / `read_only` on `PageIndexToolkit`; the multi-scope `LibraryPageIndexToolkit` facade; the `pageindex-library` template.
- `bookstore-import-tree`: `bookstore add --import` (copy or adopt-in-place, as book or notes).

### Modified Capabilities
- `bookstore-indexed-library` (catalog schema `kind`/`notes_for`, `read_section`/`get_toc` payloads, `remove`, `doctor`).
- `wikitoolkit-bookstore-conceptual-relations` (`origin: "manual"` edges from relation sheets).
- `pageindex-local-mcp-toolkit` (second template; the first is unchanged).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/bookstore/catalog.py` | modifies | `kind`, `notes_for` columns + migration; FTS `kind` column; notebook accessors |
| `knowledge/bookstore/library.py` | extends | `annotations_for`, `remap_anchors`, `find_books`, `import_tree`, notebook lifecycle, `remove` semantics |
| `knowledge/bookstore/models.py` | extends | `BookCard.kind`, `.notes_for`; `source_format` literal gains `"tree"`; `BookRelation.origin` gains `"manual"`; `SectorDraft` |
| `knowledge/bookstore/toolkit.py` + `mcp_server.py` | extends | `find_books`; annotated `read_section` / `get_toc` (read-only surface preserved) |
| `knowledge/bookstore/cli.py` | extends | `add --import`, `notebook draft`, `relate --from-notes`, `list --notes`, `remove --with-notes`, `doctor --notes` |
| `knowledge/bookstore/pageindex.py` (new) | new | `LibraryPageIndexToolkit` facade: multi-scope routing + write policy; never writes `library.db` |
| `knowledge/pageindex/toolkit.py` | extends | `write_tools`, `_authorize_write`, `read_only`; no behaviour change by default |
| `mcp/_toolkit_templates/pageindex-library.yaml` (new) | new | second template; `toolkit_server.py` untouched |
| `.claude/skills/bookstore/SKILL.md` + the Codex twin | modifies | funnel starts at `find_books`; cite notebooks as notes, never as book pages |
| `wiki/knowledge/bookstore*.md`, `pageindex-local-mcp.md` | docs | notebooks, policy, import |

No breaking change for existing callers: new columns default, new payload
keys are additive, the plain `pageindex` template is untouched.

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:331 (class Bookstore starts at :264)
def _toolkit(self, scope: str) -> PageIndexToolkit:
    # PageIndexToolkit(adapter=..., storage_dir=loc.trees_dir, lightweight_model=..., generation_grace_s=...)

# library.py:1507
async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None, force=False, *, relate=False) -> tuple[BookCard, str]
# library.py:664
def read_section(self, book_id: str, node_id: str) -> dict[str, Any]
# library.py:1784  async def _draft_card(...)
# library.py:1973  async def remove_book(self, book_id: str) -> bool
# library.py:2003  async def optimize_book(...)

# packages/ai-parrot/src/parrot/knowledge/bookstore/config.py
class LibraryLocation:  # scope, root; .db_path = root/"library.db"; .trees_dir = root/"trees"

# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:43-62  books DDL
#   book_id, title, authors, year, language, topics, summary, toc_digest, toc,
#   tree_name UNIQUE, source_path, source_sha256, source_format, page_count,
#   chapter_count, added_at, card_origin      — NO `kind`, NO `notes_for`
# catalog.py:107 book_relations ; :127 relation_judgements ; :142 communities

# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:152
class BookCard(BaseModel):  # tree_name, scope, source_path, source_format: Literal["pdf","md","txt","epub","mobi","docx"], card_origin ...
# models.py:210
class BookRelation(BaseModel):  # origin: Literal["deterministic", "llm", "community"]

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:220
class PageIndexToolkit(AbstractToolkit):
    name = "pageindex"; tool_prefix = "pageindex"
    llm_dependent_tools: frozenset[str]   # toolkit.py:265
    def __init__(self, adapter=None, storage_dir=None, ...)  # toolkit.py:275-315 (ValueError without storage_dir)
    async def tag_node(self, tree_name, node_id, categories=None, metadata=None)  # toolkit.py:1958
    # write tools present: create_tree, delete_tree, rename_tree, vacuum_tree, insert_markdown,
    #   insert_ebook, insert_content, import_file, import_pdf, import_folder, delete_node,
    #   add_node, update_node_content, update_node, tag_node, optimize(apply=True), index_segments

# packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py:118
class PageIndexNode:  # title, node_id, summary, text, doc_id (:129), revision (:130), span, locked, locked_reason, aliases, key_items ...
# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:41  tree-name regex ^[A-Za-z0-9_-]{1,128}$
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:~687  Bookstore._document_of — documents[0], raises when none
# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:203  ALTER TABLE books ADD COLUMN migration path (+ FTS rebuild)
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:53-64  available_templates() globs _toolkit_templates/*.yaml (new template auto-discovered)
# packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py:86-110  registers BookstoreToolkit.get_tools_sync() generically

# packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py:25
class SegmentStore:  # <storage_dir>/<tree>/segments/<doc_id>.<revision>.json

# packages/ai-parrot/src/parrot/mcp/toolkit_server.py:325-374
#   drop_tools = toolkit_cls.llm_dependent_tools when no llm; include/exclude filtering by tool.name

# packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:30 (__init__ at :58)
class BookstoreToolkit:  # catalog_search, list_books, get_card, get_toc, search_book, agentic_retrieve,
                         # read_section, read_pages, read_segments, outline, related_books, communities,
                         # get_community, search
```

#### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit          # library.py:35
from parrot.knowledge.pageindex.content_store import NodeContentStore     # library.py:31
from parrot.knowledge.pageindex.locks import tree_lock                    # library.py:33
from parrot.knowledge.bookstore.catalog import CatalogStore               # library.py:46
from parrot.knowledge.bookstore.config import LibraryLocation             # library.py:47
from parrot.knowledge.bookstore.config import resolve_locations           # config.py:79 (used by cli/mcp_server, not library.py)
```

#### Key Attributes & Constants
- `AbstractToolkit.llm_dependent_tools: frozenset = frozenset()` (`tools/toolkit.py:313`) — the pattern `write_tools` mirrors.
- `mcp/_toolkit_templates/pageindex.yaml` — `storage_dir: {{repo_root}}/.parrot/pageindex`, `exclude: [pageindex_agentic_retrieve]`.
- `bookstore` CLI commands today: `add`, `add-folder`, `list`, `show`, `toc`, `search`, `card`, `update`, `related`, `relate`, `communities`, `export-wiki`, `optimize`, `ask`, `doctor`, `remove`, `mcp`, `locations` (`bookstore/cli.py`).

### Does NOT Exist (Anti-Hallucination)
- ~~`books.kind` / `books.notes_for`~~ — no such columns.
- ~~`PageIndexToolkit.write_tools` / `_authorize_write` / `read_only`~~ — not present (`AbstractToolkit.exclude_tools`, `tools/toolkit.py:259-262`, exists and can back the hiding half).
- ~~`TreeNode`~~ — the node model is `PageIndexNode`.
- ~~`parrot.knowledge.bookstore.pageindex.LibraryPageIndexToolkit`~~ — new module.
- ~~`bookstore add --import`, `bookstore notebook`, `relate --from-notes`~~ — no such commands/options.
- ~~`BookstoreToolkit.find_books`~~, ~~`Bookstore.annotations_for` / `remap_anchors` / `import_tree`~~ — new.
- ~~`BookRelation.origin == "manual"`~~ — literal has three values today.
- ~~a global PageIndex index / registry~~ — PageIndex is `storage_dir`-scoped only.
- ~~any `parrot-pageindex` MCP entry in this repo's `.mcp.json`~~ — only `bookstore` is registered here.

---

## Parallelism Assessment

- **Internal parallelism**: three lanes can proceed in parallel after the
  catalog migration lands: (1) PageIndex hook + `LibraryPageIndexToolkit`
  + template, (2) notebooks/anchors/`find_books`/drafting, (3)
  `add --import`. (2) and (3) both touch `library.py` and `cli.py` —
  sequential inside one worktree or disciplined per-section edits.
- **Cross-feature independence**: shares `pageindex/toolkit.py` with
  `pageindex-toolkit-fixes` and FEAT-849 (`pageindex-toolkit-tech-debt`),
  and `bookstore/library.py` with `bookstore-reindex-atomic-swap`; land
  after those or rebase.
- **Recommended isolation**: per-spec.
- **Rationale**: one feature worktree; tasks ordered migration → hook →
  notebooks → import → MCP/skill/docs.

---

## Open Questions

- [x] One notebook per book, one per library? — *Owner: Jesus*: both; book notebooks for footnotes/notes, the library notebook for Dewey-style sectors and relation sheets.
- [x] Are sectors authoritative for "which books treat X"? — *Owner: Jesus*: yes; two-step retrieval (sector → books → anchored ToC entries), FTS/communities as fallback only.
- [x] Who populates the classification? — *Owner: Jesus*: the human, the agent on the human's instruction via PageIndex tools, and Bookstore drafting proposals from ToCs and communities.
- [x] `add --import <path>` from outside the library: copy or move? — *Owner: Claude (call)*: **copy**, original untouched; `--move` can be added later.
- [x] Node-level writes on a **book** tree: fully denied, or `tag_node` allowed for OKF typing? — *Owner: Claude (call)*: **fully denied**; OKF typing happens at ingest, and a tag that must survive re-index belongs in the notebook.
- [x] Naming constraint — *Owner: Claude (call)*: tree names cannot contain dots (`content_store.py:41`), so `<slug>_notes` and `_library_notes`; never `--`.
- [x] `find_books` first in the skill funnel? — *Owner: Claude (call)*: **always**; it falls back to FTS and says so.
- [x] `--as book` on a tree with 0 or N documents — *Owner: Claude (call)*: exactly one document required; 0 → `--as notes` only; N → refused (split out of scope v1).
- [x] Which `rel` does a relation sheet project into? — *Owner: Claude (call)*: `metadata.rel` within the existing `RelationKind`, default `parallels`, first anchor = source for directed kinds; no new kind, no `REL_WEIGHTS` change.
- [x] **Who catalogues a notebook created over the PageIndex MCP?** — *Owner: Jesus*: naming convention on disk + lazy registration by Bookstore on its next read; the MCP toolkit only reads the catalog, never writes it.
- [x] **Scopes.** — *Owner: Jesus*: one server serves both the project and the global library. *(Claude's call on the how: a Bookstore-owned facade routing to the per-scope toolkits, not a multi-directory `PageIndexToolkit`; one `_library_notes` per scope, `find_books` merges project-first, anchors carry `scope`.)*
