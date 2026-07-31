---
type: Wiki Overview
title: 'FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex'
id: doc:sdd-proposals-llmwiki-pageindex-graphindex-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot already has mature, production-ready PageIndex (~7,500 LOC) and
---

---
id: FEAT-260
title: LLM Wiki — Persistent Knowledge Base with PageIndex + GraphIndex
slug: llmwiki-pageindex-graphindex
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-26
  summary_oneline: LLM Wiki with PageIndex + GraphIndex for persistent, compounding knowledge bases
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-260/
created: 2026-06-26
updated: 2026-06-26
---

# FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — LLM Wiki implementation following Karpathy's 3-layer architecture
> **Audit**: [`sdd/state/FEAT-260/`](../state/FEAT-260/)

---

## 0. Origin

> This is an implementation of LLM wiki with several features, take as example
> to create a LLM Wiki implementation using ai-parrot, covering PageIndex +
> GraphIndex document construction, LLM-wiki with search topics, etc following
> the patterns described by Karpathy. The idea is creating a Knowledge base as
> a persistent wiki, usable for an Agent using the 3-layer architecture:
> Raw sources (immutable), The wiki (LLM-generated markdown), The schema
> (conventions + workflows). Combining wiki-style schemas, PageIndex and
> GraphIndex, combined search and the ability for LLMs to save answers and
> documents on each (llmwiki, pageindex or graphindex), add tooling for
> bookkeeping.

**Initial signals**:
- Verbs: "create", "build", "combine" → new feature
- Named entities: "LLM Wiki", "PageIndex", "GraphIndex", "Karpathy"
- Key patterns: 3-layer architecture, persistent knowledge, compounding wiki
- Acceptance criteria provided: implicit from Karpathy's design (ingest, query, lint)

---

## 1. Synthesis Summary

AI-Parrot already has mature, production-ready PageIndex (~7,500 LOC) and
GraphIndex (~5,400 LOC) modules with full agent-facing toolkits, plus 20+
document loaders, 6 vector store backends, hybrid search, community detection,
and episodic memory. **Critically, the OKF (Ontology Knowledge Framework)
already provides 80% of the "schema layer"** — concept types, typed relations,
structured frontmatter, a knowledge graph, lint health checks (orphans, broken
links, stale claims, missing pages), index.md generation, and bundle I/O.

The missing layer is the **wiki orchestrator** — an `LLMWikiToolkit` that
composes PageIndexToolkit + GraphIndexToolkit + OKFToolkit into Karpathy's
3-layer architecture: managing a curated source collection with change
detection, orchestrating multi-page wiki updates via TwoStepIngester,
providing combined PageIndex + GraphIndex search, maintaining index.md /
log.md bookkeeping (extending OKF's existing `generate_index_md()`),
supporting answer filing back into the wiki, and surfacing lint health checks
(extending OKF's existing `lint_knowledge_base()`). This is primarily a
**composition and coordination** feature built on top of OKF, not a
ground-up build.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-260/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `parrot/knowledge/pageindex/toolkit.py` | `PageIndexToolkit` | 1-1262 | Tree-based document indexing with hybrid search, 20+ tools | F001 |
| 2 | `parrot_tools/graphindex/toolkit.py` | `GraphIndexToolkit` | 63-1225 | Knowledge graph with traversal, community detection, 25+ tools | F002 |
| 3 | `parrot/knowledge/pageindex/schemas.py` | `PageIndexNode, PageIndexTree` | 118-150 | Tree node data model | F001 |
| 4 | `parrot/knowledge/graphindex/schema.py` | `UniversalNode, UniversalEdge, NodeKind` | 74-230 | Graph node/edge models with 6 node kinds | F002 |
| 5 | `parrot/knowledge/pageindex/ingest.py` | `TwoStepIngester` | 1-106 | Chain-of-thought document ingestion | F001 |
| 6 | `parrot/knowledge/pageindex/hybrid_search.py` | `HybridPageIndexSearch` | 1-462 | BM25 + LLM walk + vector search | F001 |
| 7 | `parrot/knowledge/graphindex/retriever.py` | `GraphExpandedRetriever` | 1-689 | 4-phase graph-expanded retrieval pipeline | F002 |
| 8 | `parrot/loaders/abstract.py` | `AbstractLoader` | all | Base class for 20+ document format loaders | F003 |
| 9 | `parrot/stores/abstract.py` | `AbstractStore` | 75-511 | Vector store abstraction (6 backends) | F004 |
| 10 | `parrot/tools/toolkit.py` | `AbstractToolkit` | all | Base class for agent-facing tool collections | F005 |
| 11 | `parrot/tools/filemanager.py` | `FileManagerToolkit` | all | File operations across local/S3/GCS | F005 |
| 12 | `parrot/memory/episodic/store.py` | `EpisodicMemoryStore` | all | Episode recording with semantic recall | F006 |
| 13 | `parrot/tools/working_memory/tool.py` | `WorkingMemoryToolkit` | all | Agent scratch-state management | F006 |
| 14 | `parrot/knowledge/pageindex/content_store.py` | `NodeContentStore` | 1-225 | Per-node markdown sidecar storage | F001 |
| 15 | `parrot/knowledge/graphindex/communities.py` | `detect_communities` | 1-441 | Community detection for graph clusters | F002 |
| 16 | `parrot/knowledge/pageindex/ingest.py` | `TwoStepIngester` | 43-106 | Two-model CoT ingestion (light analysis → heavy generation) | F008 |
| 17 | `parrot/knowledge/okf/ontology.py` | `ConceptType, RelationType` | 29-88 | 16 semantic types + 13 relation types | F010 |
| 18 | `parrot/knowledge/okf/frontmatter.py` | `ConceptFrontmatter` | 35-63 | Structured page metadata (type, title, id, tags, relations, provenance) | F010 |
| 19 | `parrot/knowledge/pageindex/okf/lint.py` | `lint_knowledge_base` | 91-225 | 4 health checks: orphans, broken links, missing pages, stale claims | F010 |
| 20 | `parrot/knowledge/pageindex/okf/projection.py` | `generate_index_md` | 158-197 | Auto-generated content catalog from tree structure | F010 |
| 21 | `parrot/knowledge/pageindex/okf/graph.py` | `KnowledgeGraph` | 73-237 | In-memory adjacency graph with multi-hop traversal | F010 |
| 22 | `parrot/knowledge/pageindex/okf/tools.py` | `OKFToolkit` | 46-362 | 9 agent tools: find_by_type, list_concepts, get_concept, get_related, etc. | F010 |
| 23 | `parrot/knowledge/pageindex/okf/bundle.py` | `export_okf_bundle, import_okf_bundle` | 1-584 | Round-trip bundle I/O with URI rewriting | F010 |
| 24 | `parrot/knowledge/graphindex/persist_sqlite.py` | `SQLitePersistence.is_stale` | 387-429 | File hash + mtime staleness detection for change tracking | F009 |
| 25 | `parrot/interfaces/tools.py` | `_capture_knowledge_toolkit` | 147-163 | Class-name-based toolkit stashing for REST handler access | F011 |

### 2.2 Constraints Discovered

- **PageIndex owns tree structure.** The PageIndexToolkit manages JSON trees
  with sidecar markdown. Any wiki page additions must go through its
  `insert_markdown` / `add_node` / `splice_subtree` API to maintain tree
  integrity.
  *Implication*: LLMWiki must compose PageIndexToolkit, not duplicate tree ops.
  *Evidence*: F001

- **GraphIndex uses rustworkx in-process.** The graph lives in a rustworkx
  `PyDiGraph` in memory, persisted to SQLite/ArangoDB. Graph mutations must go
  through GraphIndexToolkit's `create_node` / `link_nodes` API.
  *Implication*: Wiki-to-graph synchronization must use toolkit APIs.
  *Evidence*: F002

- **NodeKind enum is fixed.** GraphIndex defines 6 node kinds: DOCUMENT,
  SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL. A wiki page doesn't fit neatly
  into these — it's closest to DOCUMENT but has wiki-specific semantics.
  *Implication*: May need to add a `WIKI_PAGE` node kind to `NodeKind` enum,
  or use DOCUMENT with `domain_tags` for wiki metadata.
  *Evidence*: F002

- **AbstractToolkit auto-generates tools from async methods.** All public async
  methods become agent-facing tools with `tool_prefix` namespace.
  *Implication*: LLMWikiToolkit should use `tool_prefix = "wiki"` and compose
  PageIndex/GraphIndex toolkits as private attributes.
  *Evidence*: F005

- **Async-first convention.** All public methods must be async.
  *Implication*: Wiki operations (ingest, query, lint) must be async.
  *Evidence*: F005

- **Bot integration via interfaces/tools.py.** Agents discover toolkits via
  `_pageindex_toolkit` and `_graphindex_toolkit` properties. The wiki toolkit
  should follow the same pattern with `_capture_knowledge_toolkit()` detecting
  by class name string to avoid circular imports.
  *Implication*: Add `_llmwiki_toolkit` attribute, `llmwiki_toolkit` property,
  `has_llmwiki_tools` flag, and `"LLMWikiToolkit"` case to capture hook.
  *Evidence*: F005, F011

- **OKF provides the schema layer.** The OKF system already has ConceptType
  (16 types), RelationType (13 relations), ConceptFrontmatter, KnowledgeGraph,
  lint_knowledge_base(), generate_index_md(), and bundle I/O. The wiki schema
  is an OKF extension, not a parallel system.
  *Implication*: Extend ConceptType with wiki-specific types (WIKI_SUMMARY,
  WIKI_ENTITY, WIKI_COMPARISON, WIKI_SYNTHESIS). Extend RelationType with
  SUMMARIZES, CONTRADICTS, SUPERSEDES. Reuse OKFToolkit's read tools.
  *Evidence*: F010

- **TwoStepIngester uses a two-model strategy.** Cheap model for CoT analysis
  (truncated to 8K chars), expensive model for structured markdown generation.
  Content is limited to avoid token waste on long documents.
  *Implication*: Wiki ingest can follow the same pattern — Step 1 identifies
  which existing wiki pages need updating, Step 2 generates the actual updates.
  *Evidence*: F008

- **GraphIndex has atomic document replacement.** `ingest_document()` and
  `replace_document_slice()` support atomic delete-and-reinsert per source URI.
  SQLite persistence includes staleness detection via file hash + mtime.
  *Implication*: Wiki→graph sync can use source-URI-scoped replacement. Source
  collection change detection can reuse SQLite's `is_stale()` pattern.
  *Evidence*: F009

### 2.3 Recent History (Relevant)

No recent commits directly related to a wiki feature. The PageIndex and
GraphIndex modules have been stable and receiving incremental improvements
(OKF integration, embedding-guided search, community detection).

---

## 3. Probable Scope

### What's New

- **`parrot/knowledge/wiki/`** — New `wiki` subpackage within the knowledge
  module, housing the LLMWiki orchestrator class and wiki-specific data models.

- **`LLMWikiToolkit`** — Agent-facing toolkit (`tool_prefix = "wiki"`) that
  composes PageIndexToolkit + GraphIndexToolkit + OKFToolkit. Exposes wiki
  operations: ingest source, query wiki, file answer, lint wiki, manage
  index/log, browse wiki pages. Follows the `_capture_knowledge_toolkit()`
  pattern for bot integration. *Evidence*: F005, F010, F011

- **`WikiConfig`** — Pydantic configuration model defining the wiki's 3-layer
  structure: source directory, wiki directory, schema file path, page types,
  index/log file conventions, search weights. *Evidence*: F005

- **Wiki-specific ConceptTypes** — Extend OKF's `ConceptType` enum with
  `WIKI_SUMMARY`, `WIKI_ENTITY`, `WIKI_COMPARISON`, `WIKI_SYNTHESIS`,
  `WIKI_OVERVIEW` to support Karpathy's page categories (summaries, entity
  pages, concept pages, comparisons, overview). *Evidence*: F010

- **Wiki-specific RelationTypes** — Extend OKF's `RelationType` enum with
  `SUMMARIZES`, `CONTRADICTS`, `SUPERSEDES` to support cross-reference
  semantics beyond the existing REFERENCES/MAPS_TO set. *Evidence*: F010

- **`SourceCollectionManager`** — Tracks curated sources: what's been ingested,
  file hashes + mtime for change detection (reusing SQLite's `is_stale()`
  pattern), ingestion timestamps, metadata. *Evidence*: F009

- **`WikiBookkeeper`** — Maintains `index.md` (extending OKF's
  `generate_index_md()` with source counts and category breakdown) and
  `log.md` (chronological operation record with parseable prefixes).
  *Evidence*: F010

- **Combined search** — Unified search across PageIndex trees + GraphIndex
  graph + optional vector store, with result merging and reranking.
  *Evidence*: F001, F002

- **Wiki ingest orchestrator** — Multi-page update coordinator that uses
  TwoStepIngester for source processing (Step 1: identify affected pages,
  Step 2: generate updates), then orchestrates PageIndex tree mutations +
  GraphIndex sync + index/log updates atomically. *Evidence*: F008, F009

### What Changes

- **`parrot/knowledge/graphindex/schema.py`::NodeKind** — Add `WIKI_PAGE`
  variant to represent wiki-generated pages as graph nodes.
  *Evidence*: F002

- **`parrot/interfaces/tools.py`** — Add `wiki_toolkit` property and
  `has_wiki_tools` flag, following the pattern of `pageindex_toolkit` /
  `graphindex_toolkit`.
  *Evidence*: F005

- **`parrot/bots/abstract.py`** — Add `_wiki_toolkit` attribute initialization.
  *Evidence*: F005

### What's Untouched (Non-Goals)

- **PageIndex internal tree operations** — No changes to tree building,
  node splitting, or content store internals.
- **GraphIndex internal graph operations** — No changes to extractors,
  community detection, or persistence logic.
- **Loader implementations** — No changes to individual format loaders.
- **Vector store backends** — No changes to PgVector, FAISS, etc.
- **Obsidian/external tool integration** — Karpathy mentions Obsidian, Marp,
  Dataview, but these are user-side tools, not ai-parrot features.
- **Multi-tenant wiki isolation** — Out of scope for initial implementation;
  single-tenant per wiki instance is sufficient.

### Patterns to Follow

- **AbstractToolkit composition** — The wiki toolkit composes existing toolkits
  as private attributes, delegating tree/graph operations.
  *Evidence*: F005

- **Pydantic models for all structured data** — WikiConfig, WikiPage,
  SourceMetadata, etc.
  *Evidence*: F001, F002

- **Two-Step ingestion** — Follow PageIndex's TwoStepIngester pattern for
  source processing.
  *Evidence*: F001

- **Async context manager for lifecycle** — Wiki toolkit should use
  `__aenter__`/`__aexit__` for resource management.
  *Evidence*: F004

### Integration Risks

- **PageIndex + GraphIndex synchronization**: When a wiki page is created via
  PageIndex, a corresponding WIKI_PAGE node must be created in GraphIndex with
  cross-reference edges. Failure to sync creates orphaned entities.
  *Mitigation*: Wrap page creation in a transaction-like pattern with rollback
  on GraphIndex failure.
  *Evidence*: F001, F002

- **Index/log file concurrency**: If multiple agents operate on the same wiki
  concurrently, index.md and log.md become contention points.
  *Mitigation*: Use file-level locking or append-only log with periodic
  index rebuilds.
  *Evidence*: F007

- **LLM cost for multi-page updates**: A single ingest might touch 10-15 wiki
  pages (per Karpathy). Each page update requires LLM calls for summarization
  and cross-reference analysis.
  *Mitigation*: Use lightweight model for summary updates, batch LLM calls,
  support `lightweight_model` parameter (existing PageIndex pattern).
  *Evidence*: F001, F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | PageIndex provides complete tree-based document indexing with 20+ agent tools | F001 | high | Direct read of toolkit.py, 1262 lines, all methods verified |
| C2 | GraphIndex provides complete knowledge graph with 25+ agent tools | F002 | high | Direct read of toolkit.py, schema.py, retriever.py |
| C3 | 20+ loaders exist for source ingestion covering all major formats | F003 | high | Package listing confirmed; AbstractLoader interface verified |
| C4 | 6 vector store backends available with hybrid/MMR/ColBERT search | F004 | high | stores/__init__.py registry confirmed |
| C5 | AbstractToolkit pattern well-established for new toolkit creation | F005 | high | Multiple existing toolkits follow the same pattern |
| C6 | Episodic memory + working memory available for operation tracking | F006 | high | Direct read of store.py and tool.py |
| C7 | Karpathy design maps cleanly to ai-parrot's existing architecture | F007, F001, F002, F010 | high | 3-layer architecture: sources→loaders, wiki→PageIndex+OKF, graph→GraphIndex |
| C8 | NodeKind enum may need a WIKI_PAGE variant | F002 | medium | Alternative: use DOCUMENT with domain_tags metadata; either approach works |
| C9 | Combined search across PageIndex + GraphIndex is achievable | F001, F002 | high | Both have search APIs with score normalization; merging is straightforward |
| C10 | Multi-page ingest orchestration is the primary new code needed | F001, F002, F007, F008 | high | Individual page operations exist; TwoStepIngester pattern reusable; orchestration layer is missing |
| C11 | OKF already provides the wiki schema layer (ConceptType, RelationType, lint, index generation) | F010 | high | Direct read: 16 ConceptTypes, 13 RelationTypes, lint_knowledge_base() with 4 checks, generate_index_md(), OKFToolkit with 9 tools |
| C12 | TwoStepIngester (lightweight model → heavy model CoT pipeline) is the ingest mechanism | F008 | high | Direct read: ingest.py:43-106, two-model chain with 8K truncation, produces IngestedMarkdown |
| C13 | GraphIndex atomic document replacement (`replace_document_slice`) enables wiki→graph sync | F009 | high | Direct read: builder.py:287-344, SQLite staleness tracking with mtime + SHA-1 |
| C14 | Bot integration follows a documented pattern (`_capture_knowledge_toolkit` by class name string) | F011 | high | Direct read: interfaces/tools.py:147-163, two-phase registration verified across 3 files |

Distribution: **12** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Does ai-parrot already have PageIndex and GraphIndex?** — *Resolved*:
  Yes, both are mature modules with full agent toolkits (F001, F002).
- [x] **Are document loaders available for source ingestion?** — *Resolved*:
  Yes, 20+ loaders via parrot_loaders package (F003).
- [x] **Is there a toolkit pattern to follow?** — *Resolved*:
  AbstractToolkit with tool_prefix, async methods, Pydantic schemas (F005).
- [x] **Should the schema layer be built from scratch or extend OKF?** — *Resolved*:
  Extend OKF. The Ontology Knowledge Framework already provides ConceptType (16 types),
  RelationType (13 relations), ConceptFrontmatter, KnowledgeGraph, lint_knowledge_base()
  (4 checks), generate_index_md(), and OKFToolkit (9 tools). The wiki adds wiki-specific
  ConceptTypes/RelationTypes rather than building a parallel WikiSchema system (F010).
- [x] **How does ingest work — custom pipeline or reuse TwoStepIngester?** — *Resolved*:
  Reuse TwoStepIngester (lightweight model for CoT analysis, heavy model for structured
  output). Extend the two-step pattern for multi-page awareness: Step 1 identifies which
  existing pages to update, Step 2 generates the per-page updates (F008).
- [x] **How to sync wiki pages to the knowledge graph?** — *Resolved*:
  Use GraphIndex's `replace_document_slice()` for atomic per-source-URI delete-and-reinsert.
  Staleness detection via SQLite `is_stale()` (mtime + SHA-1 hash) (F009).
- [x] **How to integrate LLMWikiToolkit with bots?** — *Resolved*:
  Follow `_capture_knowledge_toolkit()` pattern: add `_llmwiki_toolkit` attribute to
  AbstractBot, add class name case to `_capture_knowledge_toolkit()`, add property +
  `has_llmwiki_tools` flag. Two-phase registration: agent_tools() in constructor,
  register_toolkit() in configure() (F011).

### Unresolved (defer to spec / implementation)

- [ ] **Should WIKI_PAGE be a new NodeKind or use DOCUMENT with domain_tags?**
  — *Owner*: tbd
  *Blocks claims*: C8
  *Plausible answers*: a) New `WIKI_PAGE` NodeKind (cleaner semantics,
  schema migration) · b) `DOCUMENT` with `domain_tags={"wiki_page": true}`
  (no schema change, less explicit)

- [ ] **Where should the wiki directory live by default?** — *Owner*: tbd
  *Blocks claims*: none
  *Plausible answers*: a) `{agents_dir}/{agent_id}/wiki/` (per-agent) ·
  b) `{storage_dir}/wiki/{wiki_name}/` (shared, named) ·
  c) User-configurable via WikiConfig

- [ ] **How should wiki-specific ConceptTypes be added to OKF?** — *Owner*: tbd
  *Blocks claims*: C11
  *Plausible answers*: a) Extend the existing `ConceptType` enum directly
  (simplest, but couples OKF to wiki) · b) Use a registry pattern allowing
  domain-specific extensions (more flexible, requires refactor) ·
  c) Use string-valued types with an OKF enum as fallback (backward-compatible)

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-260`** — *Rationale*: localization is high-confidence
(C1-C6, C11-C14), the scope is well-defined (composition layer over existing
modules), and the architectural direction is clear: extend OKF as the schema
layer, compose PageIndex + GraphIndex + OKFToolkit, reuse TwoStepIngester for
source processing, use `replace_document_slice()` for wiki→graph sync. The
spec should detail:
- LLMWikiToolkit API surface (ingest, query, lint, file_answer, browse)
- WikiConfig schema
- OKF extension: wiki-specific ConceptTypes and RelationTypes
- Combined search algorithm (PageIndex HybridSearch + GraphIndex Retriever)
- WikiBookkeeper: index.md (extending generate_index_md()) + log.md formats
- Source collection tracking (reusing `is_stale()` pattern)
- Wiki→GraphIndex synchronization protocol (`replace_document_slice()`)
- Bot integration wiring (`_capture_knowledge_toolkit()` extension)

### Alternatives

- **`/sdd-brainstorm FEAT-260`** — If you want to explore alternative
  approaches to the wiki orchestration (e.g., event-driven vs. procedural
  ingest, centralized vs. distributed index management).
- **`/sdd-task FEAT-260`** — Not recommended. This feature has multiple
  components (toolkit, config, OKF extension, search, bookkeeping, sync) that
  need spec-level design before task decomposition.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-260/state.json` |
| Source (raw) | `sdd/state/FEAT-260/source.md` |
| Findings (digests) | `sdd/state/FEAT-260/findings/F001-*.md` through `F011-*.md` |

**Budget consumed**:
- Files read: 33 / 40
- Grep calls: 16 / 25
- Git calls: 0 / 10
- Truncated: **no**
- Refinement rounds: 1 (user-requested deep dive into 4 areas: PageIndex ingest, GraphIndex writes, OKF schema layer, bot integration)

**Mode determination**: `auto` → resolved to `enrichment` (new feature:
"create", "build", "combine" verbs; no existing bug or regression).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Operator | Claude (session) |
| Reference | [Karpathy LLM Wiki Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) |

---

## Appendix A: Proposed LLMWikiToolkit API Surface

The following is a preliminary sketch of the toolkit's public methods. Each
becomes an agent-facing tool with `tool_prefix = "wiki"`.

### Core Operations (Karpathy's 3 operations)

| Tool | Description |
|------|-------------|
| `ingest_source(wiki_name, source_path, source_type?)` | Load a source, process it, create/update wiki pages, update index + log, sync to graph |
| `query(wiki_name, question, file_answer?)` | Search wiki (combined PageIndex + GraphIndex), synthesize answer. If `file_answer=True`, save the answer as a new wiki page |
| `lint(wiki_name, fix?)` | Health-check: find contradictions, orphan pages, stale claims, missing cross-refs, coverage gaps |

### Wiki Management

| Tool | Description |
|------|-------------|
| `create_wiki(wiki_name, schema?, description?)` | Initialize a new wiki with directory structure, index.md, log.md, and optional schema |
| `list_wikis()` | List all wikis managed by this toolkit |
| `get_wiki_info(wiki_name)` | Return wiki metadata: page count, source count, last updated, health status |
| `delete_wiki(wiki_name)` | Remove a wiki and its backing PageIndex tree + GraphIndex nodes |

### Page Operations

| Tool | Description |

…(truncated)…
