---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use the project areas of your
#   repository (`sdd/CONVENTIONS.md` § Project areas, or the `projects` list in
#   `sdd/config.json`). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [bookstore, pageindex, agentic-retrieval, citations, multistoresearch, reindex]
---

# Brainstorm: Bookstore inherits PageIndex stage 2 — agentic retrieval, verifiable citations in `multistoresearch`, re-index hardening

**Date**: 2026-11-09
**Author**: Jesus Lara (brainstorm drafted by Claude)
**Status**: exploration
**Recommended Option**: A

Anchored at `dev @ b0f148625e` (includes PR #2052, which moved `catalog.upsert` before `_invalidate_graph` in `add_book`). Follow-up of FEAT-843 `pageindex-agentic-retrieval` (§8: "Bookstore
`agentic_retrieve` and `multistoresearch` citations — follow-up slice") and FEAT-846
`pageindex-tree-optimizer` (ownership + `key_items` now define what `read_segments` returns to stage 2).
Re-index hardening builds on FEAT-615 `bookstore-reindex-atomic-swap` (done 2026-09-30).

---

## Problem Statement

FEAT-843 gave PageIndex a **stage 2**: after the stage-1 tree search, a bounded reading loop on a
dedicated client reads pages and paragraphs through ledger-wrapped tools and returns an
`EvidenceBundle` whose citations were validated against the stored text
(`[Report.pdf, p. 12 ¶3]`). That loop exists **only** on `PageIndexToolkit.agentic_retrieve`
(`pageindex/toolkit.py:1240`). Three callers that hold real documents cannot reach it:

1. **Bookstore** — the personal library (nine books indexed on this host today, PDF/EPUB/MOBI) exposes
   `search`, `search_book`, `read_segments`, `outline` … but no agentic tool. `BookstoreToolkit`
   (`bookstore/toolkit.py`) has zero references to `agentic` or `Citation`. An agent researching
   *"what does Marco Aurelio say about anger?"* gets node bodies and must cite by hand.
2. **`multistoresearch`** — `MultiStoreSearchToolkit` fans a query out over `SearchOrigin` adapters
   (vector / pageindex / graphindex / lancedb / wiki). There is **no Bookstore origin**, so an `Agent`
   configured with a multi-origin registry cannot see the library at all, and `OriginHit` carries
   `content` + free `metadata` but nothing that pins a hit to a revision-stable address a reader
   could re-verify.
3. **Re-index** — FEAT-615 made `Bookstore.add_book` atomic (ingest into a `--staging-` tree, then
   `rename_tree(overwrite=True)`, then `_invalidate_graph`). Ledger issue `759176f0cf1a` ("re-index
   deletes tree before new ingest succeeds") was **already fixed by FEAT-615** and only left open in the
   ledger (closed in this brainstorm, `resolved_by spec:FEAT-615`). Four hardening gaps remain:
   - `_invalidate_graph(slug)` runs on **every** `updated` import, even when the new tree has the same
     `toc_digest` — a byte-only re-import throws away every relation, judgement and the community
     partition for nothing (`library.py:1240-1241`, `:1421-1433`).
   - No per-slug lock: two concurrent `add_book` of the same source both stage and both
     `rename_tree(overwrite=True)`; last writer wins silently (`library.py:1126`, `:1229`).
   - `_sweep_reserved_trees` runs only at the start of the **next** `add_book` in that scope
     (`library.py:1107`); a staging tree left by a crash lingers until someone adds a book.
   - A crash between `rename_tree` (`:1229`) and `catalog.upsert(card)` (`:1239`; PR #2052 already moved the upsert ahead of the graph invalidation) leaves the **old**
     card (old `toc`, old `toc_digest`) over the **new** live tree; nothing detects or repairs it.

Finally, the agentic budgets (`40000` chars, `12` reads, `20` tool calls, `120 s`) are provisional;
FEAT-843 §8 asked to tune them "over Bookstore books", which only now exist on the host.

**Who is affected**: agents and MCP clients researching the library (Claude Code via `bookstore mcp`,
in-process `Agent`s with `BookstoreToolkit` or `MultiStoreSearchToolkit`), and operators re-indexing
books (`bookstore add --force`, `add-folder`).

## Constraints & Requirements

- **One stage-2 implementation.** Bookstore reuses `PageIndexToolkit.agentic_retrieve` and
  `AgenticRetriever`; no second loop, no second validator. Budgets, serialisation
  (`_agentic_lock`, one request per toolkit instance) and `stopped` semantics are inherited unchanged.
- **Degrades like Bookstore, not like PageIndex.** Without an LLM the agentic tool stays **visible**
  and errors explanatorily (the `bookstore mcp` degradation-matrix pattern, `mcp_server.py:7-18`);
  Bookstore does *not* adopt PageIndex's `llm_dependent_tools` hiding. *(decided in discovery)*
- **Origins finish inside their timeout.** `BookstoreOrigin.search()` runs stage 1 only
  (`Bookstore.search`, LLM tree-walk or BM25) plus bounded segment reads; it never runs the agentic
  loop (up to 120 s, serialised). *(decided in discovery)*
- **Citations are verifiable, not decorative.** Every citation/hit excerpt is a
  whitespace-normalised substring of the stored segment at `(doc_id, revision, seq)` with half-open
  `[start, end)`; the revision is carried so a later re-import invalidates the reference cleanly
  (FEAT-831 generations, FEAT-840 revisions).
- **No shared-model changes.** `Citation` (`pageindex/citations.py:47`) and `OriginHit`
  (`parrot/models/stores.py:79`) are untouched; Bookstore adds `book_id` / `title` / `chapter` in
  metadata and composes its own label. *(decided in discovery)*
- **`clients/base.py` untouched.** FEAT-848 `supports_tool_loop` is already enforced in
  `_agentic_client` (`pageindex/toolkit.py:1223-1238`).
- **Re-index hardening preserves FEAT-615 invariants**: reserved names (`--staging-`, `--replaced-`),
  crash sweep, `rename_tree(overwrite)` as the only publication step, cleanup of the staging tree on
  any `BaseException`.
- **Evaluation runs on the host**, not in a worker sandbox (the FEAT-845/846 sandboxes had no
  corpus, a coder invented metrics once); model `google:gemini-3.5-flash-lite`; seven of the nine books in the
  project library; numbers copied from the report into the wiki, never typed.
- Async-first, `aiohttp` only, Pydantic v2, `self.logger`, tests next to each distribution.

---

## Options Explored

### Option A: Thin delegation — per-book `agentic_retrieve`, stage-1 `BookstoreOrigin` with pinned excerpts, four targeted hardenings

Bookstore gains `Bookstore.agentic_retrieve(book_id, query, …)` that resolves the card, calls
`toolkit.agentic_retrieve(card.tree_name, query, …)` on the book's scope toolkit and **wraps** the
bundle: `book_id`, `book_title` on top; each citation enriched with `book_id`, `title`, `chapter`
(the title of the tree node whose `owned` ranges contain the citation's `seq`, with fallbacks — see
Internal Behavior §1) and a Bookstore label
`[<title>, <chapter>, <label>]`. `BookstoreToolkit.agentic_retrieve` exposes it as
`bookstore_agentic_retrieve`. Without an LLM it raises `BookstoreError("agentic retrieval requires an
LLM — set PARROT_BOOKSTORE_LLM …")`, mirroring `search` without `bm25s`.

`BookstoreOrigin(bookstore, *, scope=None, max_books=3, top_k=5, excerpt_chars=600, name="bookstore")`
implements `SearchOrigin`: `search()` calls `Bookstore.search(query, max_books, top_k)` and, for each
`(book, node_id)` hit, one `Bookstore.read_segments(book_id, node_id=node_id, max_chars=excerpt_chars)`
to obtain the node's **own** first segments; the `OriginHit.content` is the exact segment text, and
`metadata["citation"]` carries `doc_id, revision, seq, start, end, page, section, label, book_id,
title, chapter`. The excerpt is asserted with `find_any_match` before emission (a hit whose text is
not in its segment is dropped and counted in the section note). `SearchOriginKind` gains
`BOOKSTORE = "bookstore"` (additive enum value).

Re-index hardening, all inside `library.py`:
- **Graph preservation**: compute the new card's `toc_digest` before the swap; when it equals the
  existing card's digest, skip `_invalidate_graph` and keep `community_id`/`community_label` on the
  upserted card (relations describe content the TOC proves unchanged).
- **Per-slug lock, fail fast**: wrap the identity check and the ingest-to-upsert critical section in
  the FEAT-840 `tree_lock` (`pageindex/locks.py:48`) on the **live** slug with a short timeout
  (default 5 s), so a second `add_book` of the same book fails at once with a clear "re-index in
  progress" error instead of racing the rename.
- **Sweep on open**: `_sweep_reserved_trees` also runs once per scope on first `_toolkit(scope)` use
  (lazy, idempotent) and from a new `bookstore doctor` CLI that reports/sweeps reserved trees and
  card/tree drift, and lists books with no relation judgements (`--relate` runs `relate_books` on
  them; nothing else in `doctor` calls an LLM).
- **Drift detection**: `resolve_book` (or `doctor`) compares the card's `toc_digest` with
  `derive_toc(tree)` of the live tree; a mismatch is reported, and `doctor --repair` re-derives the
  TOC into the card (no re-ingest).

Plus `bookstore ask <book_id> "<query>"`, a thin CLI over the same method, and a host-run
evaluation task over **seven** books with `google:gemini-3.5-flash-lite`: the five that already
have a segment store, plus the two EPUBs re-indexed first (they are legacy trees without segments).
Three hand-written questions and five generated questions per book (56 in all), recording
`grounded`, gold hit, citations kept / rejected, `chars_read`, `tool_calls`, `stopped` and wall time.
All 56 run at the current defaults; the 21 hand-written ones also run a one-dimensional sweep
(`budget_chars` 20k / 60k, `max_reads` 8 / 16). That is 140 runs; the report fixes Bookstore's
defaults.

✅ **Pros:**
- Zero new retrieval logic: every guarantee of FEAT-843 (ledger, validator, deadline, snapshot pin) is
  inherited; Bookstore only maps `book_id → tree_name` and decorates.
- Honors every decision taken in discovery (per-book, metadata citations, stage-1 origin, visible
  tool, four hardenings, eval).
- `BookstoreOrigin` works with **no LLM** (BM25 path) and is cheap: `max_books × top_k` reads of
  `excerpt_chars`, no model call.
- Hardenings are local to `add_book` / `resolve_book`; FEAT-615 tests stay green, new ones are
  additive.

❌ **Cons:**
- Library-wide agentic questions ("which of my books…") still need the agent to call
  `bookstore_search` then `bookstore_agentic_retrieve` per book — two steps.
- The origin's excerpt is the node's **first** paragraphs, not the passage most relevant to the
  query (stage 1 ranks nodes, not segments); relevance inside the node is the reader's job.
- Adds one enum value to `parrot.models.stores.SearchOriginKind` (shared module).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | bundle / hit models | already a core dependency |
| `bm25s` (optional) | no-LLM origin path | already optional for `search_book` |
| `google-genai` | evaluation runs only | `gemini-3.5-flash-lite` verified live on 2026-11-09 |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` — `agentic_retrieve`,
  `_agentic_client`, `read_segments`, `list_documents`, `search_documents_scoped`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` — `AgenticRetriever`, `EvidenceBundle`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py` — `Citation`, `find_any_match`,
  `render_citation`
- `packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py` — `tree_lock`, `TreeLockTimeout`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — `add_book`, `_sweep_reserved_trees`,
  `_invalidate_graph`, `read_segments`, `search`, `resolve_book`, `_book_result`
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/wiki.py` — closest analog of a
  library-level origin (store handed in, FTS/vector legs, `OriginHit` construction)

---

### Option B: Library-wide agentic loop — stage 1 across the catalog, stage 2 over N books in one loop

`Bookstore.agentic_research(query, max_books)` shortlists books (`catalog_search` + `search`), then
runs **one** `AgenticRetriever` whose read tools are bound to several trees at once (tool names
prefixed per book, ledger keyed by `(tree, doc, revision)`), so the model can compare passages across
books in a single answer with cross-book citations.

✅ **Pros:**
- The most valuable user experience: one call answers "what do my books say about X" with citations
  from several books.
- Cross-book budget accounting in one ledger.

❌ **Cons:**
- Changes FEAT-843 internals: `AgenticRetriever.run` takes one `tree_name`, one `outline`, one
  `generation`; snapshot pinning (`_agentic_snapshot`) is per tree. Multi-tree pinning, multi-tree
  candidate lists and per-book generation checks are new design, not reuse.
- Cost and latency multiply by `max_books`; the 120 s deadline becomes hard to honor.
- Discovery explicitly chose per-book delegation for this slice.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | no new packages | all in `parrot.knowledge.pageindex` |

🔗 **Existing Code to Reuse:**
- `pageindex/agentic.py` — would need `run()` to accept a list of `(tree_name, outline, generation)`
- `bookstore/library.py` — `search` shortlist logic

---

### Option C: Typed citations as a `multistoresearch` first-class concept

Extend `OriginHit` with `citation: Optional[Citation]`, `SearchOrigin` with
`supports_citations: bool`, and `MultiStoreSearchToolkit` with `cited_search()` that only queries
citation-capable origins and returns a merged, deduped list of verified excerpts. `PageIndexOrigin`
and the new `BookstoreOrigin` implement it; vector / graph / wiki origins stay `False`.

✅ **Pros:**
- Cleaner typing than a metadata dict; consumers get a `Citation` they can render with
  `render_citation`.
- A uniform contract any future origin can adopt.

❌ **Cons:**
- Touches the shared `parrot.models.stores` model used by five origins and the merged BM25 reranker;
  every serialisation test of `OriginHit` changes.
- `PageIndexOrigin` would need the same segment-read decoration as Bookstore to be honest about
  `supports_citations`; scope doubles.
- Discovery chose metadata and no change to `OriginHit`.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | model extension | — |

🔗 **Existing Code to Reuse:**
- `parrot/models/stores.py` — `OriginHit`, `OriginSection`, `SearchOriginKind`
- `parrot_tools/multistoresearch/toolkit.py` — `_run_origins`, `_section_from_result`

---

### Option D (unconventional): FTS5 segment mirror in the catalog — citations without touching PageIndex at query time

At `add_book`, mirror every segment `(book_id, doc_id, revision, seq, page, section, text)` into an
FTS5 table of the catalog SQLite. `BookstoreOrigin` sets `supports_fts = True`; `fts_search` hits are
**segment rows**, each already a verifiable address with exact text — no tree read, no LLM, no
`bm25s`. Re-import replaces the mirror atomically with the swap.

✅ **Pros:**
- Paragraph-granular hits (better than node-first-paragraph excerpts) with zero PageIndex reads.
- Works fully offline; `fts_search` in `multistoresearch` gets a real paragraph-level origin.

❌ **Cons:**
- Duplicates the segment store (FEAT-840) into a second store: two sources of truth to keep in sync,
  with Don Quijote-sized books (282 k tokens in one leaf) inflating the catalog DB.
- Invalidation and generation semantics (FEAT-831) would have to be replicated in SQL.
- Orthogonal to the agentic loop; it does not deliver `bookstore_agentic_retrieve`.

📊 **Effort:** Medium (origin) + High (sync discipline)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlite3` FTS5 | paragraph index | stdlib; FTS5 available in the system SQLite |

🔗 **Existing Code to Reuse:**
- `bookstore/catalog.py` — `CatalogStore` schema, `upsert`
- `pageindex/segment_store.py` / `segments.py` — segment iteration

---

## Recommendation

**Option A** is recommended because:

- It is the only option that reuses stage 2 **as is**. FEAT-843's guarantees are subtle (exact
  clipping, admission cap, snapshot pinning, deadline including repair); Option B would re-open them
  for multi-tree reads, and Bookstore's value is in the books, not in a second retriever.
- Every discovery decision maps onto it directly: per-book tool, PageIndex `Citation` plus
  `book_id`/`title`/`chapter` metadata, stage-1 origin with pinned excerpts that work without an LLM,
  visible-but-explanatory MCP tool, and the four hardenings.
- Option C's typed citations remain reachable later: because Option A stores a full address in
  `metadata["citation"]`, a future `citation: Optional[Citation]` field can be populated from it
  without changing any origin.
- Option D is a genuine alternative for paragraph-level FTS, but it duplicates FEAT-840's store and
  does not deliver the agentic tool; it is recorded as a possible follow-up, not as part of this slice.

**Trade-offs accepted**: two-step library-wide research (search, then agentic per book); origin
excerpts are the node's leading paragraphs rather than the query-best passage; one additive enum
value in `parrot.models.stores`; budgets tuned on today's trees, which include degenerate ebook and
PDF trees still being fixed elsewhere (`0a693a57b138`, `ab5235978ad7`), so they are provisional.

---

## Feature Description

### User-Facing Behavior

**New Bookstore tool `bookstore_agentic_retrieve(book_id, query, top_k=5, draft_answer=True,
budget_chars=None, max_reads=None, timeout_s=None)`** (toolkit, MCP, and in-process). Returns the
FEAT-843 evidence bundle for that book plus `book_id`, `book_title`; every citation carries
`book_id`, `title`, `chapter`, and `rendered_citations` reads
`[Las Meditaciones de Marco Aurelio, LIBRO I, p. 5 ¶2]` (PDF, owning node) or
`[Don Quijote de la Mancha, PRIMERA PARTE, ¶12]` (MOBI, owning node, no pages); with no chapter it is
`[<title>, <label>]`. `grounded` is false
when no citation survived; `stopped` tells why the loop ended (`answered`, `budget`, `timeout`,
`no_tool_calls`). Without an LLM the tool returns a `BookstoreError` whose message names
`PARROT_BOOKSTORE_LLM`; the tool stays listed in `bookstore mcp`.

**New `multistoresearch` origin `BookstoreOrigin`.** Configured with a `Bookstore` instance (and
optional scope / book filter); `list_search_origins` shows `kind: "bookstore"`. `store_search`
returns Bookstore hits whose `content` is exact book text and whose `metadata["citation"]` is a
revision-pinned address an agent can quote or re-read with `bookstore_read_segments(book_id,
start=seq, end=seq+1)`. Without an LLM it uses BM25; without `bm25s` the origin section is `error`
with the explanatory note, the other origins are unaffected.

**Re-index behaviour.** `bookstore add --force` of a book whose TOC did not change keeps its
relations and communities (log line says so). Two concurrent re-indexes of the same book no longer
race: the second fails within seconds with `re-index of <slug> already in progress — retry when it
finishes`. `bookstore doctor` lists reserved trees, sweeps stale staging trees, reports books whose
card no longer matches the live tree and books with no relation judgements; `--repair` re-derives
drifted TOCs (deterministic, no LLM) and `--relate` runs `relate_books` on the unrelated books.

**New CLI `bookstore ask <book_id> "<query>" [--llm provider:model] [--budget-chars N] [--max-reads N]
[--timeout S] [--json]`.** Prints the drafted answer, then one rendered citation per line, then
`grounded` / `stopped` / `chars_read`; `--json` prints the full bundle. It resolves the model the same
way `bookstore optimize` does and prints the resolved `provider:model` first, because inside a Claude
Code session the default resolution picks the `claude-code` client.

**Evaluation report** at `artifacts/logs/bookstore_agentic_eval/<ts>/report.md`, with per-book
grounded rate, gold-hit rate (hand-written and generated reported separately), kept/rejected
citations, chars read, tool calls, wall time, per budget setting, plus each book's tree shape (node
count, largest leaf in tokens, whether nodes carry `owned` ranges) so a re-run after the tree fixes is
comparable. Metrics only: no book text in the report, because the Spanish translations may still be
under copyright. The chosen defaults are written into the Bookstore wiki page with the report's
sha256.

### Internal Behavior

1. `Bookstore.agentic_retrieve` → `resolve_book(book_id)` → `_toolkit(loc.scope)` →
   `await toolkit.agentic_retrieve(card.tree_name, query, …)` (inherits lock, budgets, snapshot).
   Decoration, for each `Citation`, resolves `chapter` and `section_path` in this order:
   (a) the tree node whose `owned` ranges (the field `validate_ownership` reads) contain
   `citation.seq` — `chapter` is that node's title, `section_path` the titles from the root to it;
   (b) else the segment's own `section` path (markdown/ebook segments carry one, PDF segments always
   have `section=None`); (c) else the depth-1 `TocEntry` whose `[start_page, end_page]` covers
   `page`; (d) else no chapter. On this host (a) is the normal path: every book with a segment store
   has `owned` on all its nodes but one (see Code Context, library state), and for MOBI books the
   segment `section` equals the owning node's title, so (b) only matters for trees without ownership.
   Then attach `book_id`,
   `title`, `chapter`, `section_path` and recompose `rendered_citations`. No LLM call is added.
2. `BookstoreOrigin.search(query, k)` → `Bookstore.search(query, max_books, top_k)` → for each
   per-book result with `node_id`: `Bookstore.read_segments(book_id, node_id=node_id,
   max_chars=excerpt_chars)` → first `SegmentRead`(s) → `OriginHit(content=text, metadata.citation=
   {doc_id, revision, seq, start, end, page, section, label, book_id, title, chapter}, origin_kind=
   BOOKSTORE, native_rank=i)`; `find_any_match(segment.text, content)` guards emission. Reads are
   concurrent per hit with a small semaphore; the origin's own `timeout` bounds the whole call.
3. `add_book` hardening: acquire `tree_lock(trees_dir, slug, timeout=reindex_lock_timeout_s)`
   (constructor kwarg, default 5 s) **before** the identity check (`find_by_sha` / `find_by_path`), so
   the "skipped / updated / added" decision and the swap happen under one lock, and release after
   `catalog.upsert`; compute `toc_digest` from the staging tree, compare with
   `existing.toc_digest` when `status == "updated"`; call `_invalidate_graph` only on change (and
   carry `community_id/label` otherwise). `_toolkit(scope)` triggers a one-time
   `_sweep_reserved_trees(scope)` per process. `doctor` composes `_scan_reserved_trees`,
   `_sweep_reserved_trees`, a card/tree digest comparison via `derive_toc(get_tree(tree_name))`, and
   a per-book count of `relation_judgements` rows; `--relate` calls `relate_books(ids)` (LLM by
   default, `--no-llm` passes `use_llm=False`).
4. `bookstore ask` is a CLI wrapper over `Bookstore.agentic_retrieve`; no logic of its own beyond
   model resolution and output formatting.
5. Evaluation: a host script `python -m parrot.knowledge.bookstore.agentic_eval --library <dir>
   --questions <fixture> --llm google:gemini-3.5-flash-lite [--concurrency N]`. Before the first run
   the task re-indexes the two legacy EPUBs (Zaratustra, Kierkegaard) with `bookstore add <epub>
   --force --no-llm` from `parrot-bookstore/books/`, so they get a segment store. The two
   page-extraction books are excluded: their markdown source under `/tmp` no longer exists and they
   duplicate the Analectas and Meditaciones PDFs. Questions live in a
   fixture committed under `sdd/state/<FEAT-ID>/agentic-eval-questions.json`: per book, three
   hand-written questions with a gold node (or page) and five generated ones, each produced once by
   the model from a sampled paragraph segment (≥ 40 tokens) and stored with its gold `seq`. The
   fixture holds questions and addresses only, no book text, and is generated once, not per run. A
   gold hit is a validated citation whose `seq` is the gold `seq` or is owned by the gold node.
   Concurrency uses one `Bookstore` instance per worker, because agentic retrieval is serialised per
   `PageIndexToolkit` instance (FEAT-843). The SDD task copies numbers from the report and never
   types them.

### Edge Cases & Error Handling

- **Book without segments** (legacy tree, no revision): `_document_of` already raises
  `BookstoreError("book has no segments — reindex it …")`; the agentic tool surfaces the same error
  before any LLM call; the origin skips the book with a note. Four such books exist on this host
  today (both EPUBs and both page extractions, all indexed 2026-09-06 before FEAT-840).
- **Uninformative node titles**: a MOBI without a usable table of contents yields one node titled
  `Start` (Unamuno), so its citations read `[Amor y pedagogía, Start, ¶n]`. The label is rendered as
  is; the ebook-heading fix `0a693a57b138` is what improves it.
- **Re-import during a read**: PageIndex snapshot pinning returns `stopped="stale"` /
  `RevisionUnavailableError`; Bookstore passes the bundle through; origin hits carry the revision so
  a consumer re-reading gets `RevisionMismatchError`, never silently different text.
- **No LLM / `_NullAdapter`**: `_agentic_client` raises `ValueError`; Bookstore maps it to
  `BookstoreError` with the env-var hint.
- **Provider without tool loop** (hf / jev / gemini-live): FEAT-848 `require_tool_loop` raises before
  any search; same mapping.
- **Concurrent agentic calls on one scope**: serialised by the scope toolkit's `_agentic_lock`; a
  caller whose `timeout_s` expires while waiting gets the `timeout` bundle unchanged (FEAT-843).
- **Lock held on re-index**: after `reindex_lock_timeout_s` (5 s), `TreeLockTimeout` becomes
  `BookstoreError("re-index of <slug> already in progress — retry when it finishes")`; nothing was
  read or staged, so there is nothing to clean. `add-folder` reports the book as failed and continues.
- **Citation with no resolvable chapter** (no `owned`, no `section`, no page-covering TOC entry):
  `chapter` and `section_path` are omitted and the label falls back to `[<title>, <label>]`.
- **Same-digest re-import with changed card text** (LLM re-drafted summary): relations are kept; the
  card's `summary/topics` still update; communities are recomputed only if `relate=True`.
- **Drift repair on a book whose live tree is missing**: `doctor` reports it as *orphan card*; no
  repair without the source file (`bookstore add` path).
- **Excerpt longer than the segment** or `SegmentRead.truncated`: origin uses the truncated text and
  its real `[start, end)`; `find_any_match` still holds.
- **Evaluation**: a provider error on one question is recorded as a row with `stopped="error"`, the
  run continues; the report refuses to suggest defaults if fewer than 80 % of rows completed. The
  single-node Unamuno tree and the 282k-token Don Quijote leaf are kept, as decided; their rows are
  flagged with the tree shape so they can be read separately. If an EPUB re-index fails, that book
  is reported as skipped and the run continues with the rest.

---

## Capabilities

### New Capabilities
- `bookstore-agentic-retrieval`: per-book stage-2 agentic retrieval with Bookstore-decorated,
  validated citations (toolkit + MCP), plus the `BookstoreOrigin` for `multistoresearch` with
  revision-pinned excerpts and the host-run budget evaluation.

### Modified Capabilities
- `bookstore-reindex-atomic-swap` (FEAT-615): graph preservation on unchanged `toc_digest`, per-slug
  `tree_lock`, sweep-on-open and `bookstore doctor` drift detection/repair.
- `pageindex-agentic-retrieval` (FEAT-843): §8 follow-up and budget-tuning questions closed by this
  slice; no code change in `pageindex/agentic.py`.
- `multistoresearchtool-parrotwiki` / FEAT-379 origins: one new origin and one new
  `SearchOriginKind` value; existing origins unchanged.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `bookstore/library.py` `Bookstore` | extends | `agentic_retrieve`, `_decorate_citations`, hardening in `add_book`, lazy sweep in `_toolkit`, drift check helper |
| `bookstore/toolkit.py` `BookstoreToolkit` | extends | new tool `agentic_retrieve` (11th tool); docstring is the LLM description |
| `bookstore/mcp_server.py` | modifies (docs) | degradation matrix gains the agentic row; tool count 10 → 11 |
| `bookstore/cli.py` | extends | `bookstore doctor [--repair] [--relate]` and `bookstore ask <book_id> "<query>"` |
| `bookstore/models.py` | extends (optional) | `BookCitation` **not** added; metadata dict only — decision in discovery |
| `parrot_tools/multistoresearch/origins/bookstore.py` | new | `BookstoreOrigin` |
| `parrot_tools/multistoresearch/origins/__init__.py` | extends | export |
| `parrot/models/stores.py` `SearchOriginKind` | extends | `BOOKSTORE = "bookstore"` (additive) |
| `pageindex/toolkit.py`, `pageindex/agentic.py`, `pageindex/citations.py` | depends on | read-only reuse |
| `pageindex/locks.py` `tree_lock` | depends on | per-slug lock |
| `bookstore/agentic_eval.py` | new | host-run evaluation harness (pattern: `pageindex/optimizer_eval.py`) |
| `wiki/knowledge/bookstore*.md`, `pageindex-agentic-retrieval.md` | modifies | new tool, origin, hardening, eval numbers |
| Ledger `759176f0cf1a` | closes | already fixed by FEAT-615; closed with this brainstorm |

No breaking changes: existing Bookstore tools and FEAT-615 behaviour keep their contracts; the enum
value is additive; `OriginHit`/`Citation` unchanged.

---

## Code Context

### User-Provided Code

None — all references below come from the codebase at `dev @ b0f148625e`.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                                     # line 199 region
    llm_dependent_tools: frozenset[str]  # includes "pageindex_agentic_retrieve"  # lines 206-214
    def __init__(self, adapter=None, storage_dir=None, reranker=None, lightweight_model=None, model=None, ...,
                 agentic_client: Optional[AbstractClient] = None,            # line 236
                 agentic_budget_chars: int = 40000,                          # line 237
                 agentic_max_reads: int = 12,                                # line 238
                 agentic_max_tool_calls: int = 20,                           # line 239
                 agentic_timeout_s: float = 120.0, ...)                      # line 240
    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:  # line 741
    async def list_documents(self, tree_name: str) -> list[dict[str, Any]]:  # line 970
    async def read_segments(...)                                             # line 1117
    def _agentic_client(self) -> AbstractClient:                             # line 1223
    async def agentic_retrieve(self, tree_name: str, query: str, top_k: int = 5, draft_answer: bool = True,
                               budget_chars: Optional[int] = None, max_reads: Optional[int] = None,
                               timeout_s: Optional[float] = None) -> dict[str, Any]:  # line 1240
    async def search_documents_scoped(self, query, tree_names: list[str], include_tree_context: bool = False,
                                      max_trees: int = _MAX_TREES_HARD_CAP, ...)  # line 1763
REPLACED_MARKER = "--replaced-"                                              # line 153

# From packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py
class AgenticAnswer(BaseModel): answer: Optional[str]; citations: list[ProposedCitation]   # line 65
class EvidenceBundle(BaseModel):                                             # line 72
    tree_name: str; query: str; generation: Optional[int]; candidates: list[dict]; reads: list[LedgerEntry]
    citations: list[Citation]; rejected: list[RejectedCitation]; answer: Optional[str]; grounded: bool
    tool_calls: int; chars_read: int; stopped: StopReason; usage: dict[str, int]; rendered_citations: str
def require_tool_loop(client: AbstractClient) -> None:                       # line 91
def clone_for_tools(client: AbstractClient) -> AbstractClient:               # line 107
class AgenticRetriever:                                                      # line 183
    def __init__(self, *, client: AbstractClient, model: Optional[str], read_tools: Sequence[AbstractTool],
                 load_revision: Callable[[str, str], Optional[DocumentRevision]]) -> None:  # line 188
    async def run(self, *, tree_name: str, query: str, candidates: list[dict[str, Any]], outline: dict[str, Any],
                  generation: Optional[int], budget_chars: int, max_reads: int, max_tool_calls: int,
                  deadline: float, draft_answer: bool) -> EvidenceBundle:    # line 297

# From packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py
class ProposedCitation(BaseModel):                                           # line 40
class Citation(BaseModel):                                                   # line 47
    doc_id: str; revision: str; seq: int; page: Optional[int]; ordinal: int; section: Optional[list[str]]
    start: int; end: int; excerpt: str; label: str; document: str
class RejectedCitation(BaseModel):                                           # line 63
def find_covered_match(segment_text: str, excerpt: str, covered: list[Range]) -> Optional[Range]:  # line 92
def find_any_match(segment_text: str, excerpt: str) -> bool:                 # line 102
def validate_citations(ledger: ReadLedger, load_revision: Callable[[str, str], Optional[DocumentRevision]],
                       proposed: Sequence[ProposedCitation]) -> tuple[list[Citation], list[RejectedCitation]]:  # line 107
def render_citation(citation: Citation) -> str:   # "[<document>, <label>]"  # line 182
def render_citations(citations: Sequence[Citation]) -> str:                  # line 187

# From packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq: int; kind: SegmentKind; page: Optional[int]; ordinal: int;
    section: Optional[list[str]]; level: Optional[int]; text: str; tokens: int; flags: list[str]  # line 33
class DocumentRevision(BaseModel):                                           # line 59
class SegmentRead(BaseModel): address: SegmentAddress; seq: int; kind: SegmentKind; text: str;
    start: int; end: int; truncated: bool = False; flags: list[str]          # line 97
class ReadResult(BaseModel): tree_name: str; doc_id: str; revision: str; generation: Optional[int];
    segments: list[SegmentRead]; truncated: bool; next_cursor: Optional[str]; framed: str  # line 110
def validate_ownership(nodes: Sequence[dict], revision: DocumentRevision) -> list[str]:  # line 490
#   reads node["owned"]: list of half-open [start, end) seq ranges           # lines 498-500
#   PDF segments are built with section=None                                  # line 236
def segment_text(text: str, section: list[str], *, seq_start: int = 0) -> list[Segment]:  # line 240
#   markdown/ebook segments carry section=list(section)                       # line 245

# From packages/ai-parrot/src/parrot/knowledge/pageindex/read_ledger.py
class LedgerEntry(BaseModel):                                                # line 25
class ReadLedger:  def __init__(self, *, budget_chars: int, max_reads: int) -> None:  # line 47-48

# From packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py
class TreeLockTimeout(TimeoutError):                                         # line 30
def lock_path(storage_dir: Path, tree_name: str) -> Path:                    # line 34
@asynccontextmanager
async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]:  # line 48

# From packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
_STAGING_MARKER = "--staging-"                                               # line 69
_STAGING_MAX_AGE_S = 3600                                                    # line 70
class _NullAdapter:                                                          # line 150
class Bookstore:                                                             # line 179
    def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None,
                 lightweight_model: Optional[str] = None, ...) -> None:      # line 193
    def has_llm(self) -> bool:                                               # line 216
    def _toolkit(self, scope: str) -> PageIndexToolkit:                      # line 234
    def _staging_tree_name(self, slug: str) -> str:                          # line 271
    def _scan_reserved_trees(trees_dir: Path) -> list[tuple[str, bool, float]]:  # line 276 (staticmethod)
    async def _sweep_reserved_trees(self, scope: str) -> None:               # line 293
    def list_books(self) -> list[BookCard]:                                  # line 330
    def catalog_search(self, query: str, top_k: int = 8) -> list[BookCard]:  # line 334
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]:  # line 338
    async def search_book(self, book_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:  # line 365
    async def _document_of(self, card: Any, toolkit: PageIndexToolkit) -> dict[str, Any]:  # line 404
    def _book_result(card: Any, result: dict[str, Any]) -> dict[str, Any]:  # line 412 (staticmethod)
    async def read_segments(self, book_id: str, start: Optional[int] = None, end: Optional[int] = None,
                            node_id: Optional[str] = None, max_chars: int = 12000,
                            cursor: Optional[str] = None) -> dict[str, Any]:  # line 434
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3,
                     top_k: int = 5, expand_related: bool = False) -> dict[str, Any]:  # line 495
    async def relate_books(self, book_ids: Optional[list[str]] = None, *, use_llm: bool = True,
                           communities: bool = True, communities_only: bool = False, force: bool = False,
                           resolution: float = 1.0, ...)                     # line 711
    def _clear_communities(self) -> None:                                    # line 945
    async def add_book(self, file_path: str | Path, scope: str = "project", title: Optional[str] = None,
                       authors: Optional[list[str]] = None, topics: Optional[list[str]] = None,
                       force: bool = False, *, relate: bool = False) -> tuple[BookCard, str]:  # line 1061
    def _invalidate_graph(self, book_id: str) -> None:                       # line 1421
    async def remove_book(self, book_id: str) -> bool:                       # line 1434

# add_book edit sites (library.py)
#   await self._sweep_reserved_trees(scope)                                  # line 1107
#   staging = self._staging_tree_name(slug)                                  # line 1126
#   await toolkit.rename_tree(staging, slug, overwrite=status == "updated")  # line 1229
#   catalog.upsert(card)                                                     # line 1239 (PR #2052: now before invalidation)
#   if status == "updated": self._invalidate_graph(slug)                     # lines 1240-1241

# From packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                                     # line 29
    name = "bookstore"; tool_prefix = "bookstore"                            # lines 36-37
    def __init__(self, bookstore: Bookstore, **kwargs: Any) -> None:         # line 39
    async def read_segments(self, book_id: str, start=None, end=None, node_id=None, max_chars: int = 12000,
                            cursor=None) -> dict[str, Any]:                  # line 140
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3,
                     expand_related: bool = False) -> dict[str, Any]:        # line 249

# From packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
class CatalogStore:
    def upsert(self, card: BookCard) -> None:                                # line 300
    def find_by_sha(self, sha256: str) -> Optional[BookCard]:                # line 380
    def find_by_path(self, source_path: str) -> Optional[BookCard]:          # line 386
    def delete_relations(self, book_id: Optional[str] = None, origin: Optional[str] = None) -> int:  # line 526
    def delete_judgements(self, book_id: str) -> int:                        # line 650

# From packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class BookCard(BaseModel):  # line 152; fields at lines 159-181
    book_id: str; title: str; authors: list[str]; toc_digest: str = ""; toc: list[TocEntry]; tree_name: str
    scope: Literal["project", "global"]; source_path: str; source_format: Literal[...]; page_count: Optional[int]
    chapter_count: int; added_at: str; card_origin: Literal["llm", "fallback", "manual"]
    community_id: Optional[str]; community_label: Optional[str]

# From packages/ai-parrot/src/parrot/knowledge/bookstore/config.py
Scope = Literal["project", "global"]                                         # line 29

# From packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py
def resolve_adapter(...) -> tuple[adapter, lightweight_model, client]  # all None when no LLM  # line 42

# From packages/ai-parrot/src/parrot/models/stores.py
class SearchOriginKind(Enum): VECTOR = "vector"; PAGEINDEX = "pageindex"; GRAPHINDEX = "graphindex"; WIKI = "wiki"  # line 31
class OriginHit(BaseModel): id: Optional[str]; content: str; score: Optional[float]; metadata: Dict[str, Any];
    origin: str; origin_kind: SearchOriginKind; native_rank: int           # line 79
class OriginSection(BaseModel): origin: str; origin_kind: SearchOriginKind; description: str; status: str;
    note: Optional[str]; hits: List[OriginHit]                              # line 106

# From packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py
class SearchOrigin(ABC):                                                     # line 18
    name: str; kind: SearchOriginKind; description: str; supports_fts: bool = False; timeout: Optional[float] = None
    async def search(self, query: str, k: int) -> List[OriginHit]:          # line 42 (abstract)
    async def fts_search(self, query: str, k: int) -> List[OriginHit]:      # line 54

# From packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/wiki.py
class ParrotWikiOrigin(SearchOrigin):                                       # line 21
    def __init__(self, store: "BaseWikiStore", embedder=None, category: Optional[str] = None,
                 name: str = "wiki", description: Optional[str] = None, ...)  # line 46
    async def search(self, query: str, k: int) -> List[OriginHit]:          # line 71

# From packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py
class MultiStoreSearchToolkit(AbstractToolkit):                              # line 39
    def __init__(self, origins: List[SearchOrigin], ..., k_per_origin: int = 20, ...)  # line 65
    async def store_search(...)                                              # line 85
    async def list_search_origins(self) -> List[Dict[str, Any]]:             # line 193
```

#### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER   # library.py:31 imports both
from parrot.knowledge.pageindex.agentic import AgenticRetriever, EvidenceBundle, require_tool_loop, clone_for_tools
from parrot.knowledge.pageindex.citations import Citation, find_any_match, render_citation, render_citations
from parrot.knowledge.pageindex.segments import SegmentRead, ReadResult, DocumentRevision
from parrot.knowledge.pageindex.locks import tree_lock, TreeLockTimeout
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.bookstore.toolkit import BookstoreToolkit
from parrot.knowledge.bookstore.models import BookCard, TocEntry
from parrot.models import OriginHit, SearchOriginKind            # re-exported at parrot/models/__init__.py:109 (multi-line from .stores import); used by origins/pageindex.py:26
from parrot_tools.multistoresearch.origins import SearchOrigin, PageIndexOrigin, ParrotWikiOrigin  # origins/__init__.py
from parrot_tools.multistoresearch import MultiStoreSearchToolkit  # multistoresearch/__init__.py:13
```

#### Key Attributes & Constants
- `PageIndexToolkit.llm_dependent_tools` → `frozenset[str]` containing `"pageindex_agentic_retrieve"`
  (`pageindex/toolkit.py:206-214`) — Bookstore deliberately does **not** adopt this (discovery decision).
- `PageIndexToolkit._agentic_budget_chars/_agentic_max_reads/_agentic_max_tool_calls/_agentic_timeout_s`
  (`pageindex/toolkit.py:279-282`) — the defaults Bookstore inherits until the eval fixes its own.
- `Bookstore._toolkit(scope)` builds one `PageIndexToolkit` per scope with `generation_grace_s=_STAGING_MAX_AGE_S`
  and `_NullAdapter()` when no adapter (`library.py:234-243`) → `_agentic_client` raises `ValueError` there.
- `Bookstore.search` returns `{"query", "books": [{"book_id", "title", "scope", "results": [...] | per-node items}]}`;
  the LLM branch spreads `search_documents_scoped` items (`library.py:540-575`), the BM25 branch uses
  `search_book` items `{"book_id","book_title","node_id","title","start_page","end_page","content"}` (`library.py:380-403`).
- `Bookstore.read_segments` returns `_book_result(card, ReadResult.model_dump())` → `{"book_id","book_title", **ReadResult}` (`library.py:446-460`, `:412`).
- `bookstore mcp` degradation matrix (visible tools that error without LLM/bm25s): `mcp_server.py:7-18`.
- `bookstore` CLI commands: add, add-folder, list, show, toc, search, card, update, related, relate,
  communities, export-wiki, optimize, remove, mcp, locations (`cli.py:102-654`) — **no `doctor`**.
- Existing tests to extend: `packages/ai-parrot/tests/knowledge/bookstore/{test_library,test_toolkit,test_mcp_server,test_segment_reads}.py`,
  `packages/ai-parrot-tools/tests/multistoresearch/{test_pageindex_origin,test_wiki_origin,test_toolkit}.py`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py`.
- Evaluation harness pattern: `pageindex/optimizer_eval.py` (`python -m …`, writes `artifacts/logs/<name>/<ts>/report.md`).
- Library state on this host, 2026-11-09 (`~/proyectos/parrot/parrot-bookstore/.parrot/library`):

  | book | format | segments | with `section` | nodes | nodes with `owned` |
  |---|---|---|---|---|---|
  | amor-y-pedagogia-unamuno-miguel | mobi | 1393 | 1393 | 1 | 1 |
  | analectas-confucio | pdf | 1187 | 0 | 44 | 44 |
  | critica-de-la-razon-pura-immanuel-kant | pdf | 1097 | 0 | 4 | 4 |
  | don-quijote-de-la-mancha-cervantes-miguel | mobi | 3708 | 3708 | 9 | 9 |
  | las-meditaciones-de-marco-aurelio-marco-aurelio | pdf | 1045 | 0 | 16 | 15 |
  | asi-hablo-zaratustra-friedrich-nietzsche | epub | none | — | 8 | 0 |
  | el-concepto-de-la-angustia-kierkegaard-soren | epub | none | — | 1 | 0 |
  | analectas-extraccion-por-paginas-pdf | md | none | — | 146 | 0 |
  | meditaciones-extraccion-por-paginas-pdf | md | none | — | 103 | 0 |

  Every card is `card_origin` `fallback` or `manual`; `book_relations`, `relation_judgements` and
  `communities` are empty. The Meditaciones node without `owned` is the empty "Preface" leaf of
  issue `33ad15e686e9`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.multistoresearch.origins.BookstoreOrigin`~~ — no Bookstore origin; `origins/` holds only
  `base, vector, pageindex, graphindex, wiki, lancedb`.
- ~~`SearchOriginKind.BOOKSTORE`~~ — enum has `VECTOR, PAGEINDEX, GRAPHINDEX, WIKI` only (to be added).
- ~~`Bookstore.agentic_retrieve`~~ / ~~`BookstoreToolkit.agentic_retrieve`~~ / ~~`bookstore_agentic_retrieve`~~ — not present.
- ~~`BookstoreToolkit.llm_dependent_tools`~~ — only `PageIndexToolkit` has it; Bookstore will not add it.
- ~~`parrot.knowledge.bookstore.models.BookCitation`~~ — no such model (decision: metadata, not a model).
- ~~`bookstore doctor`~~ and ~~`bookstore ask`~~ CLI commands — do not exist.
- ~~A seq → owning-node lookup helper~~ in `pageindex/` — ownership is only *validated*
  (`validate_ownership`); resolving a seq to its node is new code in Bookstore.
- ~~`parrot.knowledge.bookstore.agentic_eval`~~ — no Bookstore evaluation harness yet.
- ~~`OriginHit.citation`~~ — `OriginHit` has no citation field (Option C, rejected).
- ~~Per-slug lock in `Bookstore.add_book`~~ — no `lock`/`Lock` usage in `library.py` today.
- ~~`AgenticRetriever.run(tree_names=[...])`~~ — `run()` takes a single `tree_name` (Option B would need this).

---

## Parallelism Assessment

- **Internal parallelism**: three independent lanes — (1) `Bookstore.agentic_retrieve` + toolkit +
  MCP docs (`library.py`, `toolkit.py`, `mcp_server.py`); (2) `BookstoreOrigin` + enum + export +
  tests (`parrot_tools/multistoresearch/origins/`, `parrot/models/stores.py`); (3) re-index hardening
  + `doctor` (`library.py` `add_book`/`_toolkit`/`resolve_book`, `cli.py`). Lanes 1 and 3 both edit
  `library.py` in disjoint regions (new method vs `add_book`); the evaluation task depends on lane 1
  and runs on the host.
- **Cross-feature independence**: no in-flight spec edits `bookstore/*` or `multistoresearch/*`
  today. FEAT-853 `pageindex-optimizer-fixes` and the FEAT-850/852 PageIndex fix branches touch
  `pageindex/optimizer*.py`, `segment_store.py` and tests only — read-only dependencies here.
  `parrot/models/stores.py` is shared with every origin; the enum addition is additive.
- **Recommended isolation**: `per-spec` (one worktree), tasks ordered so lane 2 can run while lane 1
  is being reviewed.
- **Rationale**: the feature is small (≈ 6–8 tasks); the only shared file is `library.py`, and
  splitting it across worktrees would cost more merges than it saves. The eval task must run on the
  host after the worker's lane 1 lands.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] Is the re-index race still open? — *Owner: Jesus Lara*: no — FEAT-615 already implements
  staging + `rename_tree(overwrite)` + post-swap invalidation; issue `759176f0cf1a` closed with
  `resolved_by spec:FEAT-615`; this slice adds the four hardenings listed in the Problem Statement.
- [x] Shape of stage-2 inheritance in Bookstore — *Owner: Jesus Lara*: per-book
  `bookstore_agentic_retrieve` delegating to the scope toolkit; library-wide loop (Option B) rejected
  for this slice.
- [x] How citations appear in `multistoresearch` — *Owner: Jesus Lara*: new `BookstoreOrigin`,
  citation address in `OriginHit.metadata["citation"]`; `OriginHit` unchanged (Option C rejected).
- [x] What `BookstoreOrigin.search()` runs — *Owner: Jesus Lara*: stage 1 (`Bookstore.search`) plus
  bounded segment reads for exact excerpts; never the agentic loop.
- [x] MCP exposure without LLM — *Owner: Jesus Lara*: keep the Bookstore pattern — tool visible,
  explanatory error; do not adopt `llm_dependent_tools`.
- [x] Citation label for books — *Owner: Jesus Lara*: PageIndex `Citation` unchanged, Bookstore adds
  `book_id`/`title`/`chapter` in metadata and renders `[<title>, <chapter>, <label>]`.
- [x] Which hardenings — *Owner: Jesus Lara*: all four (graph preservation on same `toc_digest`,
  per-slug lock, sweep on open / `doctor`, card-vs-tree drift detection + repair).
- [x] Budget evaluation in this slice — *Owner: Jesus Lara*: yes, host run over seven of the nine indexed
  books with `google:gemini-3.5-flash-lite`; report fixes Bookstore defaults.
- [x] `SearchOriginKind` value — *Resolved in brainstorm*: add `BOOKSTORE = "bookstore"` (additive);
  reusing `PAGEINDEX` would hide which plane answered in `list_search_origins`.
- [x] `chapter` resolution — *Owner: Jesus Lara*: the owning node first (the node whose `owned`
  ranges contain the citation's `seq`), then the segment's `section` path, then the depth-1
  `TocEntry` covering the page, else omitted; `section_path` carries the full title path. Reason: the
  depth-1 TOC is useless as a chapter on this library (Analectas has one root node, Kant one node for
  pages 2–206, EPUB/MOBI have no pages).
- [x] Lock behaviour on re-index — *Owner: Jesus Lara*: fail fast. `reindex_lock_timeout_s`, default
  5 s, then a clear "re-index in progress" error; the identity check moves inside the lock.
- [x] Does `bookstore doctor` handle the relation graph — *Owner: Jesus Lara*: it reports books with
  no relation judgements; `--relate` runs `relate_books` on them; `--repair` stays deterministic and
  never calls an LLM. (Today the library has 0 relations, 0 judgements, 0 communities.)
- [x] CLI exposure — *Owner: Jesus Lara*: yes, `bookstore ask` in this slice, reusing the
  `--llm` resolution of `bookstore optimize`.
- [x] Evaluation question set — *Owner: Jesus Lara*: both — three hand-written questions with a gold
  node per book (drafted in the spec, reviewed by the owner) and five generated from sampled
  segments with a known gold `seq`, reported separately. Card `topics` are unusable as a source:
  every card is `fallback` or `manual`, so topics are TOC titles. Fixture holds questions and
  addresses only, no book text.
- [x] Which books, and when — *Owner: Jesus Lara*: seven books as indexed today, without waiting
  for `0a693a57b138` / `ab5235978ad7`: the five with a segment store, plus the two EPUBs re-indexed
  with `--force --no-llm` first. The two page-extraction duplicates are excluded because their
  source is gone. (A first answer chose all nine; it was re-asked once it turned out four of them
  have no segment store and cannot run agentic retrieval.) Consequence: the defaults are provisional
  and the report records tree shape per book for a later comparison.
- [x] Evaluation run size — *Resolved in brainstorm*: a full 3×3 grid over 56 questions would be
  504 serialised agentic runs. The plan is 56 runs at the current defaults plus a one-dimensional
  sweep of four settings over the 21 hand-written questions, 140 runs in all, with `--concurrency`
  through separate `Bookstore` instances. The spec may change the grid; the number of runs must stay
  in the report header.
- [ ] Follow-up, not this slice: re-run the evaluation after the ebook-heading and large-leaf fixes
  land and the books are re-indexed, and compare against this report. — *Owner: Jesus Lara*
