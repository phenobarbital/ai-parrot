---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns.
projects: [ai-parrot, ai-parrot-tools]
# tags: free-form kebab-case keywords for organizing specs.
tags: [pageindex, tree-optimizer, pdf-structure, agentic-retrieval, citations, prompt-injection, mcp]
---

# Brainstorm: PageIndex Tree Optimizer, Layout Structure Builder, Agentic Retrieval and Citations

**Date**: 2026-11-06
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Revision**: 3 (see *Revision History*)
**Recommended Option**: B

> Umbrella brainstorm. The user chose one document for the whole index-and-retrieval
> upgrade; the recommendation splits it into five specs (see *Capabilities*).
> Code references were verified at `dev` @ `20480877f9`, the revision 2 additions at
> `159b1993dd` and the revision 3 additions at `c8bd9cfa2d`; nothing under
> `knowledge/pageindex/` changed between them. The
> upstream comparison is against `VectifyAI/PageIndex` @ `2ac8694` (2026-11-05, v0.2.10,
> MIT), read only.

---

## Problem Statement

Our PageIndex (`packages/ai-parrot/src/parrot/knowledge/pageindex/`) is a port of the
upstream pipeline as it stood in February 2026. Since then upstream rebuilt indexing
(layout-derived structure, a search-cost tree optimizer, bottom-up summaries) and
retrieval (an agent that reads tight page ranges and cites them). We kept and extended
what we do better: any LLM through `AbstractClient`, async end to end, deterministic
hybrid retrieval, editable multi-document trees, and the OKF layer. Four gaps remain:

1. **Structure is entirely LLM-built.** `tree_parser` asks the model to find the TOC,
   assign pages, verify and repair them. It is the slowest and most expensive part of
   an import, and it is the part most exposed to instructions hidden in the document.
2. **The tree shape is never optimized.** A leaf is split only when it exceeds 10 pages
   *and* 20,000 tokens (`ConfigLoader._DEFAULTS`), so large leaves are common. BM25 sees
   only the first 4,000 characters of a node body (`_BM25_TEXT_LIMIT`), so most of a
   large leaf is invisible to lexical ranking. Siblings that share one page get the same
   page text and therefore near-identical summaries. Every node is summarized with its
   own LLM call over raw page text.
3. **Retrieval stops at the node.** `PageIndexRetriever.search` puts the whole tree JSON
   in one prompt and returns node ids; `PageIndexToolkit.retrieve` concatenates node
   markdown. Per-page markdown is computed during import and then discarded, so nothing
   can read a page range or a paragraph, and there is no citation below node level
   (`OKFToolkit.cite` returns document and page span for a concept).
4. **Document text reaches builder prompts unframed.** No call in the module uses the
   prompt-injection machinery that already protects agent input and tool output.

Affected: agents that use `PageIndexToolkit`, Bookstore (built on it), the
`multistoresearch` PageIndex origin, and anyone paying for large imports.

## Constraints & Requirements

- Keep `AbstractClient` / `PageIndexLLMAdapter`; no LiteLLM, no OpenAI Agents SDK, no
  `requests`. Async everywhere; CPU-bound work must not block the event loop.
- Keep the deterministic hybrid retrieval (BM25 + LLM walk + dense + RRF + reranker) as
  stage 1. The agentic stage is added after it, not instead of it.
- Keep editable trees, multi-document trees, sidecars and OKF `concept_id` stability.
- Structure extraction is our own code on PyMuPDF (already pinned: `pymupdf` 1.27.1,
  `pymupdf4llm` 0.0.27). Upstream Flash is not vendored and `pageindex` is not a dependency.
- Optimizer goals, in the user's words: better per-node ranking, cheaper agentic
  navigation, and **more expansion** — finer retrieval, more concepts covered, shorter
  summaries. Merging is the exception, not the default.
- Expansion creates nodes only for headings printed in the document. Concepts found in
  prose are stored as `key_items` on the leaf, each anchored to a paragraph. No
  synthetic nodes.
- The optimizer runs at import and through an explicit command on existing trees, with
  sidecar migration and a report. It never runs implicitly after an edit.
- Stage 2 is offered both ways: read tools on the toolkit for any agent, and a bounded
  internal loop that returns evidence.
- Citations carry document, page, paragraph and a verbatim excerpt, and each one is
  validated deterministically.
- Hardening reuses `parrot.security.prompt_injection` and the guardrail scoring engine,
  not upstream's regex list.
- Existing trees must keep working unchanged until someone optimizes them.
- Every write to a tree publishes a generation (revision 3): edits, imports and
  optimize alike. Publication extends the staging-tree swap that already exists; no
  separate manifest.
- PageIndex is also served as a local stdio MCP server for Claude Code, Codex and
  Antigravity (`agy`), through the existing `parrot mcp-local` and `parrot toolkits`
  machinery rather than a hand-built server.

---

## Options Explored

### Option A: Port upstream's optimizer and page tools as they are

Re-implement `tree_optimize.py`, `SummaryScheduler` and the five agent tools on top of
our adapter, with a PyMuPDF heading detector feeding them. The cost model stays in
pages: collapse cost is the node's page span, expand cost is one routing page plus the
largest child, ties merge. Retrieval reads whole pages and cites pages.

✅ **Pros:**
- A design that is already tuned and benchmarked upstream; least invention.
- Smallest conceptual distance if we want to track later upstream changes.

❌ **Cons:**
- The page is the unit of everything. Markdown, ebooks and free-text ingests have no
  pages, so three of our four input paths get nothing.
- The model is merge-biased (ties merge, a 5-page trigger before it even looks), which
  is the opposite of what the user asked for.
- Paragraph reading and verbatim-checked citations do not fit: upstream local mode
  cites pages only and validates nothing.
- Shared-page siblings need upstream's heading-offset heuristics to split text.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pymupdf` | Heading candidates, bookmarks | 1.27.1, already pinned |
| `pymupdf4llm` | Per-page markdown | 0.0.27, already pinned |

🔗 **Existing Code to Reuse:**
- `knowledge/pageindex/builder.py` — `_limited_gather`, `_LLM_SEMAPHORE`, the LLM fallback pipeline
- `knowledge/pageindex/pdf_to_markdown.py` — `extract_markdown_per_page`

---

### Option B: A segment-addressed index — one paragraph layer under everything

Introduce one new substrate: every imported document is stored as an ordered list of
**segments** (paragraph, heading, table, list, caption), each with a stable address
(`document`, `page`, `ordinal`), its text hash, token count and an injection flag.
Every other piece is then defined on segments instead of pages or node ids:

- the **structure builder** maps headings to segments, so a node is a span of segments;
- the **optimizer** measures cost in tokens over segments, which works for paged and
  unpaged sources alike, and anchors `key_items` to a segment;
- **summaries** read exactly the node's own segments, so shared pages split cleanly;
- **read tools** return pages or segment ranges, each segment labelled with its address;
- **citations** point at a segment and are checked against its stored text;
- **hardening** scores each segment once at import and frames it whenever it enters a prompt.

✅ **Pros:**
- One mechanism serves all five wanted features, and serves markdown/ebook/free-text
  sources as well as PDFs.
- Addresses do not depend on `node_id`, which `reindex_node_ids` renumbers tree-wide on
  every splice. Citations survive edits and re-optimization.
- Node-owned segment ranges partition the document (each segment has exactly one body owner), which
  removes duplicated bodies from the BM25 corpus.
- Shrinks the LLM surface: structure comes from layout, summaries skip small nodes.

❌ **Cons:**
- A new store and a migration path for existing trees; the largest of the options.
- Segment boundaries come from `pymupdf4llm` markdown, so its paragraph and table
  detection quality becomes ours.
- Scoring every segment for injection costs CPU on large books.
- Revisions 2 and 3 add a publication layer on top of the store (generations, a
  cross-process writer lock, crash recovery) that every write operation goes through.
  It makes the first spec the largest of the five.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pymupdf` | `Document.get_toc()` bookmarks, span font data | 1.27.1, already pinned |
| `pymupdf4llm` | Per-page markdown; `IdentifyHeaders` / `TocHeaders` heading maps | 0.0.27, already pinned |
| `bm25s` | Lexical index (now also over `key_items`) | 0.2.14 installed |
| `pytector` / ONNX engine | Injection scoring per segment | resolved by the guardrail module |

🔗 **Existing Code to Reuse:**
- `knowledge/pageindex/pdf_to_markdown.py` — per-page markdown is already produced at import
- `knowledge/pageindex/md_builder.py` — `parse_markdown_structure`, `sections_to_tree`
- `knowledge/pageindex/content_store.py` — sidecar layout, cache and name validation to mirror
- `knowledge/pageindex/toolkit.py` — `_batch`, `_save_node_markdown`, `_project_okf_sidecars`
- `security/prompt_injection.py` — `PromptInjectionDetector`
- `knowledge/contracts/carding.py` — `validate_obligation_clauses` (verbatim-excerpt check)
- `knowledge/pageindex/okf/tools.py` — `OKFToolkit.cite`

---

### Option C: Leave the index alone and refine at query time

No restructuring and no new builder. When stage 2 lands on a large leaf, it splits that
leaf into paragraphs on the fly, ranks them with a throwaway BM25/embedding index, reads
the best ones, and writes what it learned (concept labels and their paragraphs) back
onto the node as `key_items`. The tree improves where queries actually go.

✅ **Pros:**
- No up-front cost and no migration; value appears on the first query.
- Expansion effort follows real traffic instead of a size threshold.

❌ **Cons:**
- Retrieval writes to the tree, so results depend on query history and the index stops
  being reproducible. That breaks the "deterministic retrieval" constraint.
- Does nothing for import cost, summaries, tree shape or builder hardening.
- Cold documents stay coarse; concurrent readers race on writes.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `bm25s` | Per-leaf paragraph ranking at query time | 0.2.14 installed |

🔗 **Existing Code to Reuse:**
- `knowledge/pageindex/hybrid_search.py` — `HybridPageIndexSearch`
- `knowledge/pageindex/content_store.py` — node markdown as the paragraph source

---

### Ruled out before options: vendoring upstream Flash

Copying `pageindex/flash` (about 15k lines plus data tables) or depending on the
`pageindex` wheel was rejected by the user in discovery. The wheel also brings LiteLLM,
`openai-agents` and `requests` as hard dependencies.

---

## Recommendation

**Option B** is recommended because it is the only one that satisfies every decision
taken in discovery with one mechanism. Paragraph reading, verbatim citations, clean
summaries for shared pages, `key_items` anchors and per-segment injection flags all
need a paragraph address; Option A would bolt each on separately and still leave
unpaged sources behind, and Option C gives up determinism.

What we trade: more work up front and a new sidecar to keep consistent. That is
acceptable because the segment store is small, append-only per document, and can ship
first on its own with the read tools — useful before the optimizer exists.

Option C's idea is not discarded: traffic-driven expansion can later become a *report*
("leaves most often read in full") that feeds the explicit optimize command, without
retrieval ever writing to the tree.

---

## Feature Description

### User-Facing Behavior

**Import.** `import_pdf` (and Bookstore indexing) builds structure from the PDF itself.
The result records where the structure came from — `bookmarks`, `layout`, `hybrid`,
`llm` (fallback) or `pages` (no hierarchy found). Import is faster and makes far fewer
LLM calls; the tree has smaller leaves, shorter summaries, and `key_items` on leaves
that are continuous prose.

**Optimize an existing tree.** A new toolkit operation and CLI command optimizes a tree
or one subtree. It defaults to a dry run that prints a report: nodes before and after,
leaves over target size, expansions and merges proposed, estimated LLM calls. Applying
it migrates sidecars and reports what changed.

**Reading.** Agents get three read tools next to `search` and `retrieve`:
an outline of a tree or subtree (titles, page ranges, `key_items`, size-budgeted), a
page-range reader (`"5-7,12"`), and a segment reader (paragraph ranges). Every returned
segment carries its address so it can be cited.

**Agentic retrieve.** A new call runs stage 1 as today, hands the candidates to a
bounded loop that reads pages and paragraphs, and returns an evidence bundle: the
segments it relied on, the citations, token usage, and optionally a drafted answer.

**Citations.** Each citation includes `{document, revision, page, paragraph, start, end, excerpt}` and renders as
`[Report.pdf, p. 12 ¶3]`. Citations that fail validation are removed and listed.
The model supplies the address (which carries the revision) and the excerpt; `start`
and `end` are filled in by the validator.

**Bookstore and multistoresearch** inherit the read tools and citations.

**Local MCP server.** `parrot toolkits` installs a `pageindex` entry for Claude Code,
Codex and Antigravity, and `parrot mcp-local pageindex` serves it over stdio. The
default surface is the read side: search, outline, page and segment readers, each
result carrying citable addresses. In these hosts the host model does the stage 2
navigation itself, so the internal agentic loop is optional there. Write tools
(import, edit, optimize) are opt-in. With no LLM configured the server still serves
the deterministic tools.

### Internal Behavior

Two version terms are used below and are not interchangeable:

- **revision** — the immutable segment content of one imported document, identified by
  a content hash. Only a re-import creates a new revision. Optimizing never does, so a
  citation stays valid across optimization.
- **generation** — one published snapshot of a tree together with its node bodies, OKF
  projection and id-keyed indexes. Optimizing creates a new generation.

1. **Segment store.** At import the per-page markdown that `_extract_node_markdown`
   already computes is persisted per document and split deterministically into
   segments (blank-line blocks; tables and fenced blocks stay whole). Each document
   root node gets a stable `doc_id`. Sources without pages get segments addressed by
   ordinal only. Each immutable document revision records a content hash; segment
   addresses and read continuations include that revision. Nodes distinguish their
   subtree span from their own, possibly disjoint, segment ranges.
2. **Layout structure builder.** Sources of structure, tried in order and scored for
   confidence: embedded bookmarks (`Document.get_toc()`, rejected when non-monotonic or
   a per-page enumeration); font and layout statistics (heading levels by size and
   weight relative to body text, excluding running headers and footers; `pymupdf4llm`
   already ships `IdentifyHeaders` and `TocHeaders`); the existing LLM pipeline as
   fallback. Low-confidence headings can be spot-checked with the light adapter through
   the existing title-appearance check.
3. **Optimizer.** Deterministic passes, then LLM passes:
   - *normalize* — siblings covering the identical segment span collapse into one node;
     small leaves remain unless a contiguous merge preserves all segment ownership,
     anchors and applicable identity constraints; size alone never removes a leaf;
   - *assign ownership* — parent subtree spans widen to cover their descendants, but
     their own ranges contain only segments not owned by children, including leading,
     interstitial and trailing text. An intro leaf is allowed only for a printed
     heading; otherwise that text stays owned by the parent. No synthetic headings;
   - *expand headings* — a leaf over the target size is split at printed headings
     inside its span (first from the layout pass, then proposed by the model and
     accepted only when the title matches a heading segment);
   - *concept key_items* — a leaf still over target after that gets concept labels,
     each anchored to an existing paragraph;
   - *decide* — expand when one routing step plus the largest child costs less than
     scanning the node, in tokens; the trigger is a token target, not a page count.
     Before publication, verify that owned ranges partition each affected document
     exactly once, with no gaps or overlaps, and that all anchors still resolve.
     A subtree optimization must also preserve ownership outside its selected scope.
4. **Bottom-up summaries.** Leaves are summarized from their own segments; a leaf
   shorter than the summary limit uses its text with no LLM call; parents are composed
   from child summaries, their own segments and `key_items`. Node body sidecars contain
   only owned segments, never copies of descendant bodies. Calls run deepest first under the existing
   concurrency semaphore. Summary word limit is lowered.
5. **Indexing of key_items.** `key_items` join the BM25 text and the embedded text, and
   appear in the tree the LLM walk sees.
6. **Hardening.** Each segment is scored once at import (regex detector first; ML
   engine off the event loop). Flagged segments are stored with their flag, never
   dropped. Any document text placed in a prompt — builder, optimizer, summaries, tool
   output — is framed as data, with the instruction in the system prompt. Model output
   that names pages or headings is validated against the segments it was shown.
7. **Agentic stage.** The loop runs on `AbstractClient` with only the read tools,
   bounded by turns and by a read budget. A request-local read ledger records the
   document revision, segment address and exact half-open character ranges returned,
   measured in the stored segment text before whitespace normalization. Continuations
   retain the same revision. Readers pin one published generation for the request.
   The ledger and citation validation depend on the revision only; the generation pin
   matters for outline and node reads.
8. **Citation validation.** A citation is kept only if its revision and segment match
   the request's read ledger, its entire character range is covered by returned ranges,
   and its excerpt equals that stored slice after whitespace normalization. Adjacent
   reads may jointly cover an excerpt; unread gaps may not. Matching elsewhere in the
   segment does not suffice. Missing or mismatched revisions fail validation.
   The character range is computed by the validator, not requested from the model
   (models do not count characters reliably): it searches for the excerpt inside the
   covered ranges of the cited segment and records the first full match as `start` and
   `end`. An occurrence that lies only outside the covered ranges does not count.
9. **Optimize on existing trees.** Build a candidate generation from a pinned snapshot,
   without mutating the live tree or its sidecars. Stage the tree, segment references,
   rebuilt body sidecars, OKF projection and report together; remap unchanged bodies
   tree-wide after ID renumbering, including nodes outside the selected subtree, and
   rebuild changed bodies from owned segments. Validate ownership and anchors first,
   then publish as described under *Generation Publication*. Dry runs never publish.
10. **Local MCP server.** A packaged `pageindex` template makes the toolkit installable
    with `parrot toolkits` and servable with `parrot mcp-local`. `PageIndexToolkit`
    becomes constructible from a YAML section: it accepts the `llm_client` the runner
    passes, builds its own adapter, and declares which tools need an LLM so the rest
    are served without one. The server is a second long-lived process on the same
    storage directory, which is the concrete case the cross-process lock exists for.

### Generation Publication (every write)

Decided in revision 3. It is owned by `pageindex-segment-store`, it is used by every
write (imports, splice, delete, node and body updates, optimize), and it extends the
staging-tree swap that exists instead of adding a manifest.

- A writer works on a copy of the tree, never on the dict readers hold, so a reader
  keeps the generation it loaded for the whole request.
- Publication takes a per-tree writer lock that works across processes, checks that
  the source generation is unchanged, and rejects a stale candidate rather than
  overwrite someone else's edit.
- The swap happens only after every required file is durable. Readers see either the
  complete old generation or the complete new one.
- Id-keyed indexes follow the generation, so old BM25 entries or matrix rows cannot
  serve new ids. Per-node vectors are content-addressed and stay shared.
- The replaced generation is retained for a grace period and removed by the age-based
  sweep, instead of being deleted at once, so a reader that pinned it can finish.
- A failure before publication leaves the old generation active. Crash recovery is the
  startup sweep that already restores interrupted swaps.
- OKF projection for a candidate uses a strict path whose failure aborts publication.

What the code does today, which bounds this (checked for revisions 2 and 3):

- Nothing locks a tree. `_persist` saves without comparing the on-disk signature, so
  the last writer wins, and `_batch` persists in `finally` even after an exception; it
  is not a transaction.
- `_load_tree` hands every caller the same cached, mutable dict, and edit operations
  mutate it in place.
- Trees are also written by other processes; `_load_tree` reloads when the file's
  `(mtime, size)` changes. `knowledge/wiki/repo_cache.py::repo_lock` is an existing
  `fcntl` lock with shared and exclusive modes.
- Per-node vectors are content-addressed and survive renumbering. Only the BM25
  corpus, the tree matrix and its `node_order.json` are keyed by node id.
- Bookstore publishes a re-index through a staging tree and
  `rename_tree(overwrite=True)`, with a backup name, rollback and a startup sweep.

What that swap lacks for this purpose:

- It moves the live JSON to a backup name before moving the staged one in. For a
  moment the live name has no tree, and another process loading it gets "does not
  exist".
- It deletes the backup as soon as the swap succeeds, so nothing is retained for a
  reader that pinned the old generation.
- Its OKF projection runs after the swap and is best-effort.
- It moves the whole tree directory. Used as is for a one-node edit, it would copy
  every body file of the tree. Bodies need a stable address for per-edit generations
  to be cheap (open question).

### Edge Cases & Error Handling

- **No text layer** (scanned PDF): rejected with a clear error; OCR is out of scope.
- **No hierarchy found**: fall back to the LLM pipeline; if that also fails, one node
  per page, flagged `pages`, without optimization.
- **Running headers mistaken for headings**: text recurring at the same position across
  pages is excluded before heading detection.
- **Segment larger than a read budget** (a long table): returned truncated with a
  continuation marker, revision and the next character offset. Only returned text
  ranges enter the ledger; markers and unread remainders are not citable evidence.
- **Migration failure or concurrent edit**: leave the active generation unchanged;
  report the failure or stale snapshot and require a fresh plan before retrying.
- **Unowned or multiply owned segments**: reject the candidate before publication;
  retaining a small leaf is preferable to dropping or duplicating source text.
- **Legacy tree without a segment store**: read tools fall back to node markdown;
  citations are node-level; optimize offers only the deterministic passes or asks for
  the source file.
- **Hand-authored nodes**: the optimizer only touches subtrees that came from a
  document import (they carry `doc_id` and page ranges).
- **Re-running optimize**: a second run on an optimized tree changes nothing.
- **Model proposes an invented heading or anchor**: rejected by validation; the leaf
  stays as it was.
- **All citations fail**: the bundle is returned with an explicit ungrounded flag
  rather than an answer presented as cited.
- **Injection engine unavailable**: the regex detector is the floor; import proceeds
  and records which engine scored it.

### Required Validation Scenarios

- Run two processes on one storage directory (the MCP server and a second writer):
  concurrent edits to one tree serialize through the lock, a stale candidate is
  rejected, and a reader never observes a missing or half-moved tree during a swap.
- An ordinary edit (splice, delete, body update) publishes a generation: a reader that
  loaded the tree before the edit finishes its request on the old generation.
- Serve the toolkit from a YAML section with and without `llm`: without it, only the
  tools that need no LLM are listed, and they work.
- Inject failures during body writes, OKF projection and the publication swap; after
  reopening, the tree and every sidecar must resolve through one complete generation.
  A dry run leaves the active generation unchanged. Exercise readers during publication
  and an edit between planning and publication; stale candidates must not overwrite it.
- Optimize a subtree that renumbers later, untouched nodes; verify their bodies still
  match their identities. Rebuild split or merged bodies from their new owned ranges.
- Cover leading, middle and trailing parent text, tiny siblings and duplicate spans.
  Assert exact source-segment coverage once, preserved anchors, parent residual text
  in indexing and summaries, and no change on a second optimization with the same inputs.
- Read only the prefix of an oversized segment: a matching excerpt from its unread
  suffix must fail. Test adjacent continuation reads, an unread gap, repeated excerpts,
  whitespace normalization, and a citation or continuation from another revision.

---

## Capabilities

### New Capabilities
Proposed as five specs, in dependency order:

- `pageindex-segment-store`: per-document page and paragraph store with stable
  addresses, `doc_id` on document roots, the three read tools, per-segment injection
  flags, immutable revisions, exact read-range metadata and prompt framing helpers.
  Also generation publication for every write: copy-on-write trees, the cross-process
  writer lock, the stale check, the extended swap and the retention sweep.
- `pageindex-layout-structure`: PyMuPDF structure builder (bookmarks, font/layout
  statistics, confidence, LLM fallback) and the `structure_source` field.
- `pageindex-tree-optimizer`: normalize, segment ownership, heading expansion, concept
  `key_items`, token cost model, bottom-up summaries, the explicit optimize command
  with validated ownership, sidecar migration and report. It publishes through the
  segment store's generation path.
- `pageindex-agentic-retrieval`: the bounded stage-2 loop, the evidence bundle, the
  revision-pinned read ledger, citation model and exact-range validator.
- `pageindex-local-mcp-toolkit`: a packaged `pageindex` template for
  `parrot toolkits` / `parrot mcp-local`, `PageIndexToolkit` constructible from a YAML
  section (accepts `llm_client`, declares `llm_dependent_tools`), a read-first default
  tool surface with write tools opt-in, and results sized for a coding agent.

### Modified Capabilities
- `pageindex-content-store-and-llm-wiki-foundations`: bodies contain only owned ranges;
  parents retain any text not owned by children. Readers pin published generations.
- `pageindex-embedding-router`: embedded text and cache key include `key_items`.
- `bookstore-indexed-library`: new read tools; TOC entries rebuilt after optimize.
- `bookstore-reindex-atomic-swap`: its swap becomes the shared publication path (lock,
  stale check, retained backup, no window without a live tree); optimize runs on the
  staging tree before the swap.
- `expose-toolkits-as-local-mcp`: one more packaged template.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/pageindex/builder.py` | modifies | Layout builder becomes the default path; LLM pipeline kept as fallback; prompts framed |
| `knowledge/pageindex/toolkit.py` | extends | Read tools, optimize, agentic retrieve; `import_pdf` persists segments and `doc_id`; every write operation becomes copy-on-write and publishes a generation; constructor accepts `llm_client` |
| `knowledge/pageindex/hybrid_search.py` | modifies | `_flatten_corpus` adds `key_items`; bodies use owned segments only, including parent residual text; caches follow generations |
| `knowledge/pageindex/embedding_store.py` | modifies | `content_key` input changes; existing vectors are recomputed once; the matrix and node order follow the generation |
| `knowledge/pageindex/schemas.py` | extends | `key_items`, `doc_id`, `structure_source`, subtree span and owned segment ranges on nodes (model already allows extras) |
| `knowledge/pageindex/tree_ops.py` | extends | Restructuring operations that keep `concept_id` stable |
| `knowledge/pageindex/okf/` | depends on | Sidecars re-projected; `cite` can return paragraph addresses |
| `knowledge/bookstore/` | extends | Read tools exposed; reindex integrates optimize; its swap and sweep are shared with PageIndex publication |
| `mcp/_toolkit_templates/` | extends | New `pageindex.yaml` template; no change to the runner, the installer or the host adapters |
| `parrot_tools/multistoresearch/origins/pageindex.py` | extends | Results may carry citations |
| `security/prompt_injection.py`, `bots/guardrails/builtin/prompt_injection.py` | depends on | Needs a public way to obtain the ML scoring engine |
| Storage layout | extends | Revisioned segment files and staged generations published through the extended swap; legacy files remain readable until explicit migration |
| Dependencies | none | Everything needed is already pinned |

No breaking change for existing trees: every new field is optional and old trees take
the fallback paths.

---

## Code Context

### User-Provided Code

None. The user gave decisions, not code (see resolved Open Questions).

### Verified Codebase References

Paths are relative to `packages/ai-parrot/src/parrot/` unless stated.

#### Classes & Signatures
```python
# knowledge/pageindex/builder.py
DEFAULT_LLM_CONCURRENCY = 16                                   # line 57
_LLM_SEMAPHORE: contextvars.ContextVar[...]                    # line 60
async def _limited_gather(...)                                 # line 65
async def check_title_appearance_in_start_concurrent(...)      # line 683
async def process_large_node_recursively(node, page_list, opt, adapter, light_adapter=None) -> dict  # line 1366
async def tree_parser(page_list, opt, adapter, light_adapter=None) -> list[dict]                     # line 1436
async def generate_node_summary(node: dict, adapter) -> str    # line 1496  (one call per node, raw node['text'])
async def generate_summaries_for_structure(structure, adapter) # line 1510
async def build_page_index(doc: str | BytesIO, adapter, options=None,
                           light_adapter=None, llm_concurrency=DEFAULT_LLM_CONCURRENCY) -> dict  # line 1545
def _extract_node_markdown(doc, structure) -> dict[str, str]   # line 1622 (calls extract_markdown_per_page, keeps only the per-node map)

# knowledge/pageindex/utils.py
def get_page_tokens(pdf_path, model="gpt-4o", pdf_parser="PyMuPDF") -> list[tuple[str, int]]  # line 130
def find_node_by_id(data, node_id) -> Optional[dict]           # line 353
def post_processing(structure, end_physical_index) -> list[dict]  # line 426 (a parent's end_index stops at its first child)
def validate_and_truncate_physical_indices(...)                # line 568 (range check only)
class ConfigLoader:                                            # line 761
    _DEFAULTS = {"max_page_num_each_node": 10, "max_token_num_each_node": 20000, ...}

# knowledge/pageindex/pdf_to_markdown.py
def extract_markdown_per_page(pdf_path, *, images_dir=None, image_format="png",
                              dpi=150, image_size_limit=0.05) -> list[tuple[int, str]]  # line 39
def build_node_markdown_map(structure, pages) -> dict[str, str]  # line 211

# knowledge/pageindex/md_builder.py
def parse_markdown_structure(md_text: str) -> list[dict]       # line 58
def sections_to_tree(sections: list[dict]) -> list[dict]       # line 138
def thin_tree(...)                                             # line 183
async def md_to_tree(...)                                      # line 254

# knowledge/pageindex/schemas.py
class TreeSearchResult(BaseModel): thinking: str; node_list: list[str]   # line 107
class PageIndexNode(BaseModel):                                # line 118
    title; node_id; start_index; end_index; summary; prefix_summary; text; line_num; nodes
    model_config = {"extra": "allow"}

# knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                                     # line 42
    async def ask(self, prompt, structured_output=None, temperature=0.0, system_prompt=None) -> str  # line 61
    async def ask_structured(...)                              # line 99
    async def ask_with_finish_info(...)                        # line 151
    async def ask_json(...)                                    # line 201

# knowledge/pageindex/retriever.py
class PageIndexRetriever:                                      # line 11
    async def search(self, query: str) -> TreeSearchResult     # line 38 (whole tree JSON in one prompt)
    async def retrieve(self, query, pdf_pages=None) -> str     # line 81

# knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:                                   # line 52
    def mark_dirty(self) -> None                               # line 119
    def _flatten_corpus(self) -> tuple[list[str], list[str]]   # line 145 (title + summary + body[:_BM25_TEXT_LIMIT])
    async def search(self, query, top_k=10, use_bm25=True, use_llm_walk=True, use_vec=False,
                     use_embedding_walk=None, rerank=False) -> list[dict]  # line 288

# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                       # line 54
    def _project_okf_sidecars(self, tree_name, tree) -> None   # line 254
    def get_tools(self, permission_context=None, resolver=None) -> list  # line 366
    async def _batch(self, tree_name)                          # line 393 (async context manager)
    async def search(self, tree_name, query, top_k=10, ..., categories=None, metadata_filter=None)  # line 554
    async def retrieve(self, tree_name, query, top_k=5) -> str # line 621
    async def search_documents_scoped(self, tree_names, query, ...)  # line 658
    async def import_pdf(self, tree_name, pdf_path, parent_node_id=None,
                         with_summaries=True, with_doc_description=False) -> dict  # line 930
    def _save_node_markdown(self, tree_name, original_id_to_node, node_markdown) -> None  # line 980
def _capture_node_id_object_map(subtree) -> dict[str, dict]    # line 1331
    # added for revision 2 (persistence and publication):
    def _tree_signature(self, tree_name) -> tuple[int, int] | None  # line 182 ((st_mtime_ns, st_size) of the tree JSON)
    def _load_tree(self, tree_name) -> dict[str, Any]          # line 198 (reloads on a changed signature; returns the cached, mutable dict)
    def _persist(self, tree_name) -> None                      # line 237 (save, mark BM25 dirty, project OKF; no signature check)
    async def rename_tree(self, src, dst, *, overwrite=False) -> dict[str, Any]  # line 443 (backup name + rollback)
    # line 1002: self._content_store.save(...) runs immediately inside a batch, not deferred

# knowledge/pageindex/store.py
class JSONTreeStore:                                           # line 23
    def save(self, tree_name, tree) -> None                    # line 63 (temp file + os.replace, line 81)
    def rename(self, src, dst) -> None                         # line 97

# knowledge/pageindex/content_store.py
class NodeContentStore:                                        # line 38
    def _node_path(self, tree_name, node_id) -> Path           # line 81  -> <dir>/<tree_name>/<node_id>.md
    def save(self, tree_name, node_id, markdown) -> None       # line 111 (plain write_text, not atomic)
    def load(self, tree_name, node_id) -> Optional[str]        # line 118
    def rename_tree(self, src, dst) -> bool                    # line 175 (os.replace of the tree directory)

# knowledge/wiki/repo_cache.py
async def repo_lock(lock_path: Path, *, timeout: float, shared: bool = False)  # line 53 (fcntl file lock, async context manager)

# added for revision 3 (local MCP serving); paths relative to packages/ai-parrot/src/parrot/
# mcp/local_cli.py
def mcp_local(...)                                             # line 214 ("Serve NAME as a local stdio MCP server")
# mcp/local_server.py
class StdioMCPServer(LocalMCPServerBase):                      # line 54
# mcp/toolkit_config.py
class ToolkitSection(BaseModel):                               # line 20
    class_path (alias "class"); enabled; kwargs; include; exclude; llm; llm_kwargs; env
# mcp/toolkit_server.py
def create_toolkit_mcp_server(...)                             # line 258
    # line 341: kwargs["llm_client"] = llm_client  (how the configured LLM reaches the toolkit)
    # with no `llm`, tools named in the class's llm_dependent_tools are dropped
# mcp/toolkit_seed.py
def available_templates() -> ...                               # line 53 (packaged templates in mcp/_toolkit_templates/)
# mcp/toolkit_install.py
def install_toolkits(...)                                      # line 163 (seed the section and register it with hosts)
# mcp/hosts.py
class ClaudeAdapter(HostAdapter):                              # line 58  (repo .mcp.json)
class CodexAdapter(HostAdapter):                               # line 121 (repo .codex/config.toml)
class GoogleAdapter(HostAdapter):                              # line 178 (Antigravity: user-global ~/.gemini/config/mcp_config.json + repo plugin file)
# tools/toolkit.py
    llm_dependent_tools: frozenset = frozenset()               # line 313 (AbstractToolkit default)
# knowledge/pageindex/toolkit.py
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir, reranker=None, ..., **kwargs)  # line 92 (adapter is required)
# knowledge/bookstore/mcp_server.py
    server = StdioMCPServer(...)                               # line 101 (Bookstore builds its own stdio server by hand)
# knowledge/bookstore/cli.py
def mcp(...)                                                   # line 588
# knowledge/bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                       # line 29

# knowledge/pageindex/embedding_store.py
class NodeEmbeddingStore:                                      # line 42
    @staticmethod
    def content_key(model_id: str, title: str, summary: str) -> str  # line 94
    def invalidate_tree(self, tree_name) -> None               # line 330

# knowledge/pageindex/tree_ops.py
def reindex_node_ids(tree) -> None                             # line 22 (renumbers every node_id; concept_id untouched)
def splice_subtree(target, subtree, parent_node_id=None) -> list[str]  # line 89
def delete_node(tree, node_id) -> bool                         # line 131

# knowledge/pageindex/okf/tools.py
    def cite(self, concept_id: str) -> dict                    # line 255 (document, pages, url from node["source"])

# knowledge/okf/ontology.py
class SourceProvenance(BaseModel): document: str; pages: Optional[list[int]]; url: Optional[str]  # line 144

# security/prompt_injection.py
class PromptInjectionDetector:                                 # line 102
    def strip_framework_patterns(self, text: str) -> str       # line 198
    def detect_threats(self, text: str) -> List[Dict[str, Any]]  # line 213
    def sanitize(self, text, strict=True, replacement="[FILTERED_CONTENT]") -> Tuple[str, List[Dict]]  # line 266

# bots/guardrails/builtin/prompt_injection.py
class _InjectionScoringEngine(Protocol):                       # line 167  (module-private)
    def score(self, text: str) -> float
def _resolve_injection_engine(force_reresolve: bool = False) -> _InjectionScoringEngine | None  # line 514 (module-private)
class PromptInjectionGuardrail(Guardrail):                     # line 544
    def __init__(self, strict_mode=True, block_on_threat=False,
                 injection_probability_threshold=0.98, scan_tool_output=False, **kwargs)
    def _wrap_flagged_input(text, threats) -> str              # line 770 (<potentially_unsafe_input> wrapper)

# knowledge/bookstore/library.py
_STAGING_MARKER = "--staging-"                                 # line 68
    def _staging_tree_name(self, slug: str) -> str             # line 269
    async def _sweep_reserved_trees(self, scope: str) -> None  # line 291 (restores interrupted swaps, sweeps old staging trees)
    def get_toc(self, book_id: str) -> dict[str, Any]          # line 341
    def read_section(self, book_id: str, node_id: str) -> dict[str, Any]  # line 367

# knowledge/contracts/carding.py
def validate_obligation_clauses(clauses, bodies, *, node_id=None)  # line 503 (keeps only verbatim excerpts)

# clients/base.py
    async def ask(self, prompt, model, ..., system_prompt=None, history=None,
                  structured_output=None, tools=None, use_tools=None, ...)  # line 1944
```

#### Verified Imports
```python
from parrot.knowledge.pageindex import (
    build_page_index, md_to_tree, PageIndexRetriever, PageIndexLLMAdapter,
    JSONTreeStore, NodeContentStore, extract_markdown_per_page,
    splice_subtree, delete_node, reindex_node_ids,
    HybridPageIndexSearch, PageIndexToolkit, PageIndexLoader,
)  # knowledge/pageindex/__init__.py
from parrot.security.prompt_injection import (
    PromptInjectionDetector, SecurityEventLogger, ThreatLevel, max_threat_level,
)  # as imported at bots/guardrails/builtin/prompt_injection.py:48
```

#### Key Attributes & Constants
- `hybrid_search._BM25_TEXT_LIMIT = 4000`, `_RERANK_TEXT_LIMIT = 2000`, `_RRF_K = 60` (module constants)
- `pymupdf` 1.27.1: `pymupdf.Document.get_toc` exists (checked in the venv)
- `pymupdf4llm` 0.0.27: `helpers/pymupdf_rag.py` defines `IdentifyHeaders` (line 71),
  `TocHeaders` (line 167) and `to_markdown(..., hdr_info=None, ...)` (line 303)
- `import_pdf` returns `{tree_name, new_node_ids, doc_name, doc_description}`; its
  docstring also promises `pages`, which the returned dict does not contain

### Does NOT Exist (Anti-Hallucination)
Checked by searching every `.py` under `knowledge/pageindex/`:
- ~~`key_items`~~ — no node field, no code reads or writes it
- ~~`tree_optimize` / `optimize_tree` / `merge_tree` / `merge_same_page`~~ — no optimizer of any kind
- ~~intro nodes, `cover_subtree_ranges`~~ — parent ranges stop at the first child
- ~~`read_pages` / `get_page_content` / a page or segment store~~ — per-page markdown is
  not persisted after import; only `<tree>/<node_id>.md`
- ~~a stable `doc_id` or stored source path on imported subtrees~~ — `pdf_path` is used
  for the build and not recorded by `import_pdf`
- ~~any use of `prompt_injection`, `PromptInjectionDetector` or text framing in the builder~~
- ~~`get_toc(` or font-span extraction in pageindex~~ — bookmarks and layout are unused today
- ~~a paragraph-level citation model or validator~~ — only `OKFToolkit.cite` (node level)
- ~~a public accessor for the ML injection engine~~ — the one found, `_resolve_injection_engine`, is module-private
- ~~`pageindex` (upstream wheel), `pageindex.flash`~~ — not a dependency and not to be added

Added for revision 2, checked recursively over `knowledge/pageindex/`:
- ~~a lock around tree writes~~ — no `asyncio.Lock`, thread lock or file lock on trees;
  the only lock is `NodeEmbeddingStore._cache_lock`, which guards an in-memory cache
- ~~a generation manifest, document revisions, reader pinning~~ — a tree is one JSON
  file plus `<tree>/<node_id>.md`
- ~~a stale-write check~~ — `_persist` does not compare the on-disk signature before saving

Added for revision 3:
- ~~a `pageindex` template in `mcp/_toolkit_templates/`~~ — the nine packaged templates
  are bounded-source, browsing, database-query, lsp, memory, querysource, scraping,
  sdd-coder and targeted-writer
- ~~`llm_client` support in `PageIndexToolkit`~~ — nothing in `knowledge/pageindex/`
  reads `llm_client`, `adapter` is a required argument, and the class declares no
  `llm_dependent_tools`, so it cannot be served from a YAML section today

---

## Parallelism Assessment

- **Internal parallelism**: Good after the first spec. `pageindex-segment-store` is the
  foundation and must land first. `pageindex-layout-structure` and
  `pageindex-agentic-retrieval` then depend only on it and can run in parallel.
  `pageindex-tree-optimizer` needs the segment store and benefits from the layout
  builder's heading candidates, so it goes after or alongside layout.
  Revision 3 settles the condition revision 2 raised: generation publication, the
  writer lock and reader pinning belong to `pageindex-segment-store`, so every later
  spec can rely on them. `pageindex-local-mcp-toolkit` also depends only on the first
  spec and runs in parallel with the other three; it gains tools as they land.
  The cost is that the first spec now rewrites every write operation in `toolkit.py`.
  The other four should branch after it merges, not alongside it.
- **Cross-feature independence**: `toolkit.py` (1,418 lines) is touched by four of the
  five specs and `builder.py` by two; these are the merge hot spots. No unmerged remote
  branch for pageindex or bookstore existed when this was written.
- **Recommended isolation**: `per-spec` — one worktree per spec, tasks sequential inside.
- **Rationale**: The specs are separable by module, but within each one the tasks share
  `toolkit.py` or `builder.py`, so parallel tasks inside a spec would mostly conflict.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] Scope of this brainstorm — *Owner: Jesus Lara*: one umbrella covering optimizer, structure builder, summaries, agentic retrieval, citations and hardening.
- [x] What the optimizer optimizes — *Owner: Jesus Lara*: per-node ranking quality and agentic navigation cost, biased toward expansion: finer retrieval, more concepts covered, shorter summaries.
- [x] How far expansion goes — *Owner: Jesus Lara*: nodes only for printed headings; concepts become `key_items` anchored to a paragraph; no synthetic nodes.
- [x] When the optimizer runs — *Owner: Jesus Lara*: at import, plus an explicit command for existing trees that migrates sidecars and reports.
- [x] Where stage 2 lives — *Owner: Jesus Lara*: both read tools on the toolkit and a bounded internal loop.
- [x] Citation guarantee — *Owner: Jesus Lara*: reference plus verbatim excerpt, validated.
- [x] How to get layout-based structure — *Owner: Jesus Lara*: our own extractor on PyMuPDF; no vendored Flash, no `pageindex` dependency.
- [ ] Confirm the five-spec split and its order, or merge/split differently (the first spec has grown: segments, read tools, hardening and generation publication) — *Owner: Jesus Lara*
- [ ] Addressing for sources without pages (markdown, ebook, free text): ordinal-only segments, or virtual pages per chapter? — *Owner: Jesus Lara*
- [ ] Legacy trees with no source file on record: deterministic passes over node markdown only, or require re-import? — *Owner: Jesus Lara*
- [ ] Is "came from a document import" the right rule for what the optimizer may touch, or do curated trees need an explicit lock flag? — *Owner: Jesus Lara*
- [ ] OKF identity when the optimizer creates or removes nodes: new `concept_id` for new nodes is clear; do removed ones need an alias record? — *Owner: Jesus Lara*
- [ ] Injection policy: score every segment with the ML engine or only regex-suspect ones; and for a flagged segment, frame-and-flag (proposed) versus redact versus abort the import? — *Owner: Jesus Lara*
- [ ] Where the public accessor for the ML injection engine should live (`parrot.security`?) — *Owner: Jesus Lara*
- [ ] How the internal loop runs tools: a small `Agent` from `parrot.bots`, or the client-level tool loop (`ask(tools=..., use_tools=...)`)? Not verified in this brainstorm. — *Owner: Jesus Lara*
- [ ] Default sizes (target leaf tokens, minimum leaf, summary word limit) and the evaluation corpus and metrics used to set them — *Owner: Jesus Lara*
- [ ] May `key_items` labels be abstractive, or must each be a phrase found in its anchor paragraph? — *Owner: Jesus Lara*
- [ ] Bookstore: re-optimize the existing library automatically on upgrade, or opt in per book? — *Owner: Jesus Lara*

Raised by the review of revision 2:

- [x] Which spec owns generation publication, the writer lock and reader pinning — *Owner: Jesus Lara*: `pageindex-segment-store`.
- [x] Do edit operations also publish a generation, or only optimize — *Owner: Jesus Lara*: every write publishes a generation.
- [x] Generations as a new manifest, or as an extension of the existing swap — *Owner: Jesus Lara*: extend the staging tree plus `rename_tree` swap.
- [ ] Retention of old generations follows the existing age-based sweep. Which age, and is it the same as for staging trees (one hour today)? — *Owner: Jesus Lara*
- [ ] Old document revisions after a re-import: how many are kept, given that a stored citation to a deleted revision can no longer be checked? — *Owner: Jesus Lara*
- [ ] "No change on a second optimization" with LLM passes: record a per-node stamp (input hash and settings) so finished nodes are skipped, or limit the guarantee to the deterministic passes? — *Owner: Jesus Lara*
- [ ] What triggers a merge now that size alone never removes a leaf: only duplicate or empty spans? Is "minimum leaf" still a setting, as a floor for expansion? — *Owner: Jesus Lara*
- [ ] How a parent's disjoint own ranges are rendered as one body (order, gap markers) for `retrieve`, summaries and BM25. — *Owner: Jesus Lara*

Raised by revision 3:

- [x] A local MCP server for PageIndex — *Owner: Jesus Lara*: yes, as its own related spec, stdio, for Claude Code, Codex and `agy`.
- [ ] Body storage once every edit publishes a generation: keep `<tree>/<node_id>.md` and copy the directory per generation, or give bodies a stable address (owned segment ranges for imported nodes, `concept_id` for hand-authored ones) so a generation is one atomic JSON replace and nothing is remapped after renumbering? Proposed: the stable address. — *Owner: Jesus Lara*
- [ ] MCP storage location: one directory per repository (under `.parrot/`), or a user-level library shared across repositories as Bookstore's scopes do? — *Owner: Jesus Lara*
- [ ] MCP default tool surface: read-only with write tools opt-in (proposed), or import and optimize enabled from the start? — *Owner: Jesus Lara*
- [ ] Is the internal agentic loop exposed over MCP at all, given that the host model already navigates with the read tools? — *Owner: Jesus Lara*
- [ ] Does the Bookstore stdio server stay separate, or move onto the same template mechanism later? — *Owner: Jesus Lara*
- [ ] Is a server with no `llm` configured (BM25 and read tools only) a supported default? PDF import needs an LLM until the layout builder lands. — *Owner: Jesus Lara*

---

## Revision History

| Rev | Date | Commit | Summary |
|---|---|---|---|
| 1 | 2026-11-06 | `e29f046315` | Initial brainstorm. |
| 2 | 2026-11-06 | `159b1993dd`, review in `c8bd9cfa2d` | Segment ownership replaces intro leaves and size-based folding. Document revisions and range-exact citation validation. Optimize publishes a staged generation instead of mutating in place. Required validation scenarios. The review then defined revision and generation, made citation offsets validator-computed, limited generation scoping to id-keyed indexes, recorded what the persistence code does today, corrected the spec-order note and added eight open questions. |
| 3 | 2026-11-06 | this commit | Decisions: `pageindex-segment-store` owns generation publication; every write publishes a generation; publication extends the existing staging swap instead of a manifest. New fifth spec `pageindex-local-mcp-toolkit` (stdio, for Claude Code, Codex and `agy`) on the existing `parrot mcp-local` machinery. Recorded what the swap lacks, the MCP code references and seven open questions. |
