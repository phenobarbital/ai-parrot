<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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
directory, `<repo_root>` passed as `project_root` for determinism).

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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml
packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
packages/ai-parrot/src/parrot/knowledge/bookstore/config.py
packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py
packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py
packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py
packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py
packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
packages/ai-parrot/src/parrot/mcp/toolkit_server.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
