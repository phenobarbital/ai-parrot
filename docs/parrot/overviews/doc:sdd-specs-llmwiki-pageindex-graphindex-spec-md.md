---
type: Wiki Overview
title: 'Feature Specification: LLM Wiki — Persistent Knowledge Base with PageIndex
  + GraphIndex'
id: doc:sdd-specs-llmwiki-pageindex-graphindex-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI agents need a persistent, compounding knowledge base — not just ephemeral
relates_to:
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.lint
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.tools
  rel: mentions
- concept: mod:parrot.knowledge.wiki
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: LLM Wiki — Persistent Knowledge Base with PageIndex + GraphIndex

**Feature ID**: FEAT-260
**Date**: 2026-06-26
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Proposal**: `sdd/proposals/llmwiki-pageindex-graphindex.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI agents need a persistent, compounding knowledge base — not just ephemeral
context. Following Karpathy's 3-layer LLM wiki architecture, agents should
maintain a curated wiki of LLM-generated markdown pages (summaries, entity
pages, concept comparisons, syntheses) that grows with every ingested source.
The wiki must combine tree-based document indexing (PageIndex) with knowledge
graph traversal (GraphIndex) for rich retrieval, use the existing OKF ontology
framework as the schema layer, and provide tools for bookkeeping (index.md,
log.md), health checks (lint), and answer filing.

AI-Parrot already has mature PageIndex (~7,500 LOC) and GraphIndex (~5,400 LOC)
modules, plus OKF for structured ontology. What's missing is the **orchestration
layer** — an `LLMWikiToolkit` that composes these into Karpathy's 3-layer
architecture and adds wiki lifecycle management.

### Goals

- Implement Karpathy's 3-layer architecture: Raw Sources (immutable), Wiki
  (LLM-generated markdown), Schema (OKF-based conventions)
- Provide the 3 core operations: **Ingest** (source → multi-page wiki update),
  **Query** (combined search → synthesize → optionally file answer),
  **Lint** (health-check extending OKF's `lint_knowledge_base()`)
- Compose existing toolkits (PageIndexToolkit + GraphIndexToolkit + OKFToolkit)
  rather than duplicating functionality
- Support combined search across PageIndex trees and GraphIndex graph
- Maintain bookkeeping artifacts: `index.md` (content catalog) and `log.md`
  (operation chronicle)
- Track source collection with change detection (staleness via mtime + SHA-1)
- Synchronize wiki pages to GraphIndex nodes via `replace_document_slice()`
- Integrate with bots via the established `_capture_knowledge_toolkit()` pattern

### Non-Goals (explicitly out of scope)

- **PageIndex internal changes** — no modifications to tree building, node
  splitting, or content store internals
- **GraphIndex internal changes** — no modifications to extractors, community
  detection, or persistence logic
- **Loader implementations** — no changes to individual format loaders
- **Vector store backends** — no changes to PgVector, FAISS, etc.
- **Obsidian/external tool integration** — Karpathy mentions Obsidian, Marp,
  Dataview, but these are user-side tools, not ai-parrot features
- **Multi-tenant wiki isolation** — single-tenant per wiki instance for v1
- **Runtime fallback-on-failure** — rejected in proposal analysis; composition
  of stable toolkits doesn't need fallback chains

---

## 2. Architectural Design

### Overview

`LLMWikiToolkit` is a composition-based orchestrator that delegates all tree
operations to `PageIndexToolkit`, all graph operations to `GraphIndexToolkit`,
and all schema/ontology operations to `OKFToolkit`. It adds:

1. **Wiki lifecycle management** — create/delete/list wikis, each backed by a
   PageIndex tree + GraphIndex subgraph + source manifest
2. **Multi-page ingest orchestration** — uses `TwoStepIngester` (lightweight
   model for analysis, heavy model for generation), then coordinates tree
   mutations + graph sync + bookkeeping updates
3. **Combined search** — merges `HybridPageIndexSearch` results (BM25 + LLM
   walk) with `GraphExpandedRetriever` results (seed → expand → community),
   applies score normalization and optional reranking
4. **Wiki lint** — extends OKF's `lint_knowledge_base()` with wiki-specific
   checks (source coverage, cross-reference consistency, category completeness)
5. **Answer filing** — saves query answers back as wiki pages when requested
6. **Bookkeeping** — `WikiBookkeeper` maintains `index.md` (extending OKF's
   `generate_index_md()`) and `log.md` (append-only operation chronicle)

The schema layer is OKF itself, extended with wiki-specific `ConceptType` and
`RelationType` values. No separate WikiSchema system is needed.

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        LLMWikiToolkit                               │
│  tool_prefix = "wiki"                                               │
│  Bot integration: _capture_knowledge_toolkit("LLMWikiToolkit")      │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │  Ingest   │  │  Query   │  │   Lint    │  │  WikiBookkeeper  │  │
│  │ Pipeline  │  │ Pipeline │  │ (OKF lint │  │  index.md        │  │
│  │ (TwoStep  │  │          │  │  + wiki   │  │  (extend OKF's   │  │
│  │  Ingester)│  │          │  │  checks)  │  │  generate_index) │  │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘  │  log.md          │  │
│       │              │              │         └──────┬───────────┘  │
│  ┌────▼──────────────▼──────────────▼───────────────▼────────────┐  │
│  │              Combined Search Layer                            │  │
│  │  PageIndex HybridSearch ←──merge──→ GraphIndex Retriever      │  │
│  │  (BM25 + LLM walk)                 (seed→expand→community)   │  │
│  └──────┬──────────────────────┬──────────────────┬──────────────┘  │
│         │                      │                  │                 │
│  ┌──────▼───────────┐  ┌──────▼───────────┐  ┌───▼──────────────┐  │
│  │ PageIndexToolkit  │  │ GraphIndexToolkit│  │  OKFToolkit      │  │
│  │ (tree structure,  │  │ (knowledge graph,│  │  (schema layer:  │  │
│  │  sidecar markdown,│  │  communities,    │  │   ConceptType,   │  │
│  │  TwoStepIngester) │  │  replace_slice,  │  │   RelationType,  │  │
│  │                   │  │  is_stale())     │  │   KnowledgeGraph,│  │
│  └───────────────────┘  └──────────────────┘  │   lint, index)   │  │
│                                               └──────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Storage Layer                                                  │ │
│  │  sources/           wiki/                  OKF extensions       │ │
│  │  ├── raw docs       ├── index.md           ├── WIKI_SUMMARY    │ │
│  │  ├── .manifest.json ├── log.md             ├── WIKI_ENTITY     │ │
│  │  ├── staleness      ├── entities/          ├── WIKI_COMPARISON │ │
│  │  │   (mtime+SHA-1)  ├── concepts/          ├── SUMMARIZES      │ │
│  │  └── (immutable)    ├── summaries/         ├── CONTRADICTS     │ │
│  │                     └── comparisons/       └── SUPERSEDES      │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PageIndexToolkit` | composes (private attr) | Delegates all tree ops: create_tree, insert_markdown, search, etc. |
| `GraphIndexToolkit` | composes (private attr) | Delegates graph ops: create_node, link_nodes, search_hybrid, etc. |
| `OKFToolkit` | composes (private attr) | Delegates schema ops: lint, find_by_type, list_concepts, etc. |
| `TwoStepIngester` | uses (via PageIndexToolkit) | Source processing: CoT analysis → structured markdown |
| `HybridPageIndexSearch` | uses (via PageIndexToolkit) | BM25 + LLM walk search |
| `GraphExpandedRetriever` | uses (via GraphIndexToolkit) | Graph-expanded retrieval |
| `SQLitePersistence.is_stale()` | reuses pattern | Source staleness detection (mtime + SHA-1) |
| `SQLitePersistence.replace_document_slice()` | calls | Wiki→graph atomic sync |
| `AbstractBot._capture_knowledge_toolkit()` | extends | Add `"LLMWikiToolkit"` case |
| `generate_index_md()` | extends | Wiki index.md with source counts and categories |
| `lint_knowledge_base()` | extends | Add wiki-specific checks |
| `NodeKind` | extends | Add `WIKI_PAGE` variant |
| `ConceptType` | extends | Add wiki-specific concept types |
| `RelationType` | extends | Add wiki-specific relation types |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path
from enum import Enum


class WikiPageCategory(str, Enum):
    """Karpathy's wiki page types."""
    SUMMARY = "summary"
    ENTITY = "entity"
    CONCEPT = "concept"
    COMPARISON = "comparison"
    OVERVIEW = "overview"
    SYNTHESIS = "synthesis"
    ANSWER = "answer"


class WikiConfig(BaseModel):
    """Configuration for a single wiki instance."""
    wiki_name: str
    storage_dir: Path
    source_dir: Optional[Path] = None
    page_categories: list[WikiPageCategory] = Field(
        default_factory=lambda: list(WikiPageCategory)
    )
    search_weights: dict[str, float] = Field(
        default_factory=lambda: {"pageindex": 0.6, "graphindex": 0.4}
    )
    lightweight_model: Optional[str] = None
    model: Optional[str] = None


class SourceManifestEntry(BaseModel):
    """Tracks an ingested source document."""
    source_id: str
    source_uri: str
    file_hash: str
    mtime: float
    ingested_at: str
    pages_generated: list[str]
    status: str = "ingested"


class WikiSearchResult(BaseModel):
    """Unified search result from combined search."""
    node_id: str
    title: str
    score: float
    source: str  # "pageindex" | "graphindex"
    snippet: str
    category: Optional[WikiPageCategory] = None


class WikiLintReport(BaseModel):
    """Extended lint report with wiki-specific checks."""
    okf_report: dict  # from lint_knowledge_base()
    orphan_sources: list[str]
    stale_sources: list[str]
    uncovered_sources: list[str]
    cross_ref_issues: list[dict]
    total_issues: int
```

### New Public Interfaces

```python
class LLMWikiToolkit(AbstractToolkit):
    """Orchestrates PageIndex + GraphIndex + OKF into Karpathy's 3-layer wiki."""

    tool_prefix: str = "wiki"

    def __init__(
        self,
        pageindex_toolkit: PageIndexToolkit,
        graphindex_toolkit: GraphIndexToolkit,
        okf_toolkit: OKFToolkit,
        config: WikiConfig,
        **kwargs,
    ) -> None: ...

    # --- Core Operations (Karpathy's 3) ---

    async def ingest_source(
        self,
        wiki_name: str,
        source_path: str,
        source_type: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def query(
        self,
        wiki_name: str,
        question: str,
        file_answer: bool = False,
        mode: str = "combined",
    ) -> dict[str, Any]: ...

    async def lint(
        self,
        wiki_name: str,
        fix: bool = False,
    ) -> WikiLintReport: ...

    # --- Wiki Management ---

    async def create_wiki(
        self,
        wiki_name: str,
        description: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def list_wikis(self) -> list[dict[str, Any]]: ...

    async def get_wiki_info(
        self,
        wiki_name: str,
    ) -> dict[str, Any]: ...

    async def delete_wiki(
        self,
        wiki_name: str,
    ) -> dict[str, Any]: ...

    # --- Page Operations ---

    async def browse_pages(
        self,
        wiki_name: str,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict[str, Any]]: ...

    async def read_page(
        self,
        wiki_name: str,
        page_id: str,
    ) -> dict[str, Any]: ...

    async def create_page(
        self,
        wiki_name: str,
        title: str,
        content: str,
        category: str,
        related_pages: Optional[list[str]] = None,
    ) -> dict[str, Any]: ...

    async def update_page(
        self,
        wiki_name: str,
        page_id: str,
        content: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def delete_page(
        self,
        wiki_name: str,
        page_id: str,
    ) -> dict[str, Any]: ...

    # --- Source Management ---

    async def list_sources(
        self,
        wiki_name: str,
    ) -> list[dict[str, Any]]: ...

    async def get_source_info(
        self,
        wiki_name: str,
        source_id: str,
    ) -> dict[str, Any]: ...

    async def reingest_source(
        self,
        wiki_name: str,
        source_id: str,
    ) -> dict[str, Any]: ...

    # --- Search ---

    async def search(
        self,
        wiki_name: str,
        query: str,
        mode: str = "combined",
    ) -> list[WikiSearchResult]: ...

    async def find_related(
        self,
        wiki_name: str,
        page_id: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]: ...

    # --- Bookkeeping ---

    async def get_index(self, wiki_name: str) -> str: ...
    async def get_log(self, wiki_name: str, last_n: int = 50) -> str: ...
    async def rebuild_index(self, wiki_name: str) -> dict[str, Any]: ...
```

---

## 3. Module Breakdown

### Module 1: Wiki Data Models

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`
- **Responsibility**: Pydantic models — WikiConfig, WikiPageCategory,
  SourceManifestEntry, WikiSearchResult, WikiLintReport
- **Depends on**: pydantic, parrot.knowledge.okf.ontology (ConceptType)

### Module 2: OKF Schema Extensions

- **Path**: `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` (modify)
- **Responsibility**: Add wiki-specific values to ConceptType and RelationType
  enums. Add `WIKI_PAGE` to GraphIndex's NodeKind.
- **Depends on**: existing ontology.py, graphindex/schema.py

### Module 3: Source Collection Manager

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`
- **Responsibility**: Track ingested sources — manifest (JSON), file hash +
  mtime staleness detection (reusing `is_stale()` pattern), ingestion status.
- **Depends on**: Module 1 (SourceManifestEntry)

### Module 4: Wiki Bookkeeper

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py`
- **Responsibility**: Maintain `index.md` (extending OKF's `generate_index_md()`
  with source counts and category breakdown) and `log.md` (append-only
  operation chronicle with parseable timestamp + operation prefixes).
- **Depends on**: Module 1, OKF `generate_index_md()`

### Module 5: Combined Search

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/search.py`
- **Responsibility**: Merge results from `HybridPageIndexSearch` and
  `GraphExpandedRetriever`, normalize scores, apply configurable weights,
  optionally rerank. Return unified `WikiSearchResult` list.
- **Depends on**: Module 1, PageIndexToolkit, GraphIndexToolkit

### Module 6: Wiki Ingest Orchestrator

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py`
- **Responsibility**: Multi-page ingest pipeline — load source via loaders,
  process via TwoStepIngester (Step 1: identify affected pages, Step 2:
  generate updates), coordinate PageIndex tree mutations, sync to GraphIndex
  via `replace_document_slice()`, update manifest + index + log.
- **Depends on**: Modules 1, 3, 4, PageIndexToolkit, GraphIndexToolkit

### Module 7: LLMWikiToolkit

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py`
- **Responsibility**: Agent-facing toolkit (`tool_prefix = "wiki"`) composing
  PageIndexToolkit + GraphIndexToolkit + OKFToolkit. Exposes all wiki
  operations as async methods that become agent tools. Manages wiki lifecycle.
- **Depends on**: Modules 1-6, AbstractToolkit, PageIndexToolkit,
  GraphIndexToolkit, OKFToolkit

### Module 8: Bot Integration Wiring

- **Path**: `packages/ai-parrot/src/parrot/interfaces/tools.py` (modify),
  `packages/ai-parrot/src/parrot/bots/abstract.py` (modify)
- **Responsibility**: Add `_llmwiki_toolkit` attribute, `llmwiki_toolkit`
  property, `has_llmwiki_tools` flag, and `"LLMWikiToolkit"` case to
  `_capture_knowledge_toolkit()`.
- **Depends on**: Module 7

### Module 9: Wiki Package Init + Exports

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py`
- **Responsibility**: Package initialization, export all public symbols
  (LLMWikiToolkit, WikiConfig, WikiPageCategory, models).
- **Depends on**: Modules 1, 7

### Module 10: Tests

- **Path**: `tests/knowledge/wiki/`
- **Responsibility**: Unit + integration tests for all modules.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_wiki_config_defaults` | 1 | WikiConfig has correct defaults for categories, weights |
| `test_wiki_config_validation` | 1 | Rejects invalid search weights, missing fields |
| `test_source_manifest_entry` | 1 | SourceManifestEntry serialization round-trip |
| `test_concept_type_wiki_values` | 2 | New ConceptType values exist and are valid |
| `test_relation_type_wiki_values` | 2 | New RelationType values exist and are valid |
| `test_node_kind_wiki_page` | 2 | WIKI_PAGE NodeKind variant works |
| `test_source_manager_add_track` | 3 | Adding a source creates manifest entry with hash |
| `test_source_manager_staleness` | 3 | Detects stale sources when file changes |
| `test_bookkeeper_index_generation` | 4 | Generates index.md with source counts |
| `test_bookkeeper_log_append` | 4 | Appends operations to log.md with timestamps |
| `test_combined_search_merge` | 5 | Merges results with score normalization |
| `test_combined_search_mode_filter` | 5 | Respects mode=pageindex/graphindex/combined |
| `test_ingest_creates_pages` | 6 | Ingesting a source creates wiki pages |
| `test_ingest_updates_manifest` | 6 | Manifest updated after ingest |
| `test_ingest_syncs_to_graph` | 6 | Graph nodes created for wiki pages |
| `test_toolkit_tool_prefix` | 7 | tool_prefix is "wiki" |
| `test_toolkit_create_wiki` | 7 | Creates wiki with directory structure |
| `test_toolkit_query_file_answer` | 7 | Query with file_answer=True creates a page |
| `test_toolkit_lint` | 7 | Lint returns combined OKF + wiki report |
| `test_bot_capture_wiki_toolkit` | 8 | _capture_knowledge_toolkit detects LLMWikiToolkit |
| `test_bot_has_wiki_tools` | 8 | has_llmwiki_tools returns True when toolkit registered |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_ingest_query` | Ingest a markdown source → query → verify answer references source content |
| `test_ingest_reingest_cycle` | Ingest source → modify source → reingest → verify pages updated |
| `test_combined_search_ranking` | Ingest multiple sources → combined search → verify ranking uses both indexes |
| `test_lint_detects_issues` | Create wiki with orphan pages → lint → verify issues reported |

### Test Data / Fixtures

```python
@pytest.fixture
def wiki_config(tmp_path):
    return WikiConfig(
        wiki_name="test-wiki",
        storage_dir=tmp_path / "wiki-storage",
    )

@pytest.fixture
def sample_source(tmp_path):
    source = tmp_path / "sources" / "article.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Neural Networks\n\nA neural network is...")
    return source
```

---

## 5. Acceptance Criteria

- [ ] `LLMWikiToolkit` creates wikis with directory structure (sources/, wiki/,
  index.md, log.md)
- [ ] `ingest_source` processes a raw document into multiple wiki pages via
  TwoStepIngester
- [ ] Ingested sources are tracked in a manifest with file hash + mtime for
  staleness detection
- [ ] Wiki pages are synchronized to GraphIndex as WIKI_PAGE nodes via
  `replace_document_slice()`
- [ ] `query` performs combined search across PageIndex + GraphIndex with
  configurable weights
- [ ] `query` with `file_answer=True` saves the answer as a new wiki page
- [ ] `lint` runs OKF's `lint_knowledge_base()` plus wiki-specific checks
  (orphan sources, stale sources, cross-reference issues)
- [ ] `index.md` is auto-generated extending OKF's `generate_index_md()` with
  source counts and category breakdown
- [ ] `log.md` is append-only with parseable timestamp + operation entries
- [ ] OKF `ConceptType` extended with wiki-specific values (WIKI_SUMMARY,
  WIKI_ENTITY, WIKI_COMPARISON, WIKI_SYNTHESIS, WIKI_OVERVIEW)
- [ ] OKF `RelationType` extended with SUMMARIZES, CONTRADICTS (SUPERSEDES
  already exists)
- [ ] GraphIndex `NodeKind` extended with WIKI_PAGE
- [ ] Bot integration: `_capture_knowledge_toolkit()` detects `LLMWikiToolkit`
- [ ] Bot integration: `has_llmwiki_tools` property and `llmwiki_toolkit`
  accessor work correctly
- [ ] All unit tests pass: `pytest tests/knowledge/wiki/ -v`
- [ ] No breaking changes to existing PageIndex, GraphIndex, or OKF APIs
- [ ] All public classes and methods have Google-style docstrings + type hints
- [ ] Async throughout — no blocking I/O

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# PageIndex
from parrot.knowledge.pageindex import (     # verified: pageindex/__init__.py
    PageIndexToolkit,                        # line 42
    PageIndexNode,                           # line 24
    TwoStepIngester,                         # line 40
    IngestedMarkdown,                        # line 41
    HybridPageIndexSearch,                   # line 38
    JSONTreeStore,                           # line 33
    NodeContentStore,                        # line 34
    md_to_tree,                              # line 27
    splice_subtree,                          # line 36
)

# GraphIndex
from parrot.knowledge.graphindex import (    # verified: graphindex/__init__.py
    UniversalNode,                           # exported
    UniversalEdge,                           # exported
    NodeKind,                                # exported
    EdgeKind,                                # exported
    SQLitePersistence,                       # exported
    BuildResult,                             # exported
    IngestResult,                            # exported
)

# OKF
from parrot.knowledge.okf.ontology import (  # verified: okf/ontology.py
    ConceptType,                             # line 29
    RelationType,                            # line 60
)
from parrot.knowledge.okf.frontmatter import ConceptFrontmatter  # line 35
from parrot.knowledge.pageindex.okf.lint import lint_knowledge_base  # line 91
from parrot.knowledge.pageindex.okf.projection import generate_index_md  # line 158
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph  # line 73
from parrot.knowledge.pageindex.okf.tools import OKFToolkit  # line 46

# Tools
from parrot.tools.toolkit import AbstractToolkit  # line 207
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):  # line 207
    tool_prefix: Optional[str] = None  # line 258
    prefix_separator: str = "_"  # line 261
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]:  # line 385

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):  # line 50
    name: str = "pageindex"  # line 85
    tool_prefix: str = "pageindex"  # line 86
    def __init__(self, adapter, storage_dir, reranker=None, lightweight_model=None,
                 model=None, default_bm25_k=20, ..., **kwargs) -> None:  # line 88
    async def list_trees(self) -> list[str]:  # line 373
    async def create_tree(self, tree_name, doc_name=None) -> dict:  # line 377
    async def search(self, tree_name, query, top_k=10, ...) -> list[dict]:  # line 414
    async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None) -> dict:  # line 692
    async def insert_content(self, tree_name, content, parent_node_id=None, hint=None) -> dict:  # line 730

# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit):  # line 63
    def __init__(self, graph, faiss_index, node_map, node_id_list, client=None,
                 assembler=None, embedder=None, nodes=None, signal_config=None) -> None:  # line 95

…(truncated)…
