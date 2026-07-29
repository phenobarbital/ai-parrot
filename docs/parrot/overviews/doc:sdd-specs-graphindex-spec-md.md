---
type: Wiki Overview
title: 'Feature Specification: GraphIndex — Structured Knowledge Graph Indexing'
id: doc:sdd-specs-graphindex-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'ai-parrot agents currently rely on three relatively flat retrieval surfaces:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.ontology
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.loaders.abstract
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.graphindex
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex — Structured Knowledge Graph Indexing

**Feature ID**: FEAT-187
**Date**: 2026-05-19
**Author**: Jesús Lara
**Status**: approved
**Target version**: 0.26.0
**Proposal**: `sdd/proposals/graphindex.proposal.md`
**Research state**: `sdd/state/FEAT-187/`

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot agents currently rely on three relatively flat retrieval surfaces:

- **PageIndex** for hierarchical PDF/Markdown trees with LLM-driven tree-search retrieval — great for *"find the right section in this document"*.
- **Vector stores** for embedding similarity — great for *"find chunks that look like this query"*.
- **OntologyGraphStore** for tenant-isolated ArangoDB graphs — great when there is a hand-crafted, domain-specific schema.

What is missing is a **structured-knowledge graph** layer that unifies these into a single navigable surface across source code (Python in v1; TypeScript and Svelte in v1.1), structured documentation (PDF, DOCX, Markdown, web, ebook, audio, video transcripts via `ai-parrot-loaders`), and skill files (`SKILL.md`).

Today, an agent that needs to answer *"what policy clause governs the `tenant_create` function?"* must search those surfaces independently and reconcile in prose. A graph with explicit cross-domain references makes the same answer a one-hop traversal.

### Goals

- Provide a unified knowledge graph that spans code, documents, and skills within a single tenant.
- Deliver an agent-facing toolkit (`GraphIndexToolkit`) with graph traversal, hybrid search, centrality, and path query methods.
- Reuse existing infrastructure: `OntologyGraphStore` for persistence, `parrot.embeddings` for vector computation, `ai-parrot-loaders` for content acquisition, `PageIndex` for hierarchical document trees.
- Generate a deterministic `GRAPH_REPORT.md` injectable into agent system prompts via `KNOWLEDGE_LAYER`.
- Support two refresh paths: batch full-document reindex (Flowtask) and incremental per-document reindex (API).
- Maintain tenant isolation consistent with the existing ontology model.
- Keep the design language-extensible: Python parsing in v1, TypeScript/Svelte grammars in v1.1 with no architectural rework.

### Non-Goals (explicitly out of scope)

- **MCP server exposure** — initial consumers are parrot agents on the platform. MCP wrapper deferred.
- **Level 2 cross-domain resolution** (LLM verification of inferred edges) — deferred to v2.
- **File-watcher-based atomic change detection** — deferred to v2.
- **Community detection** (`leidenalg` + `igraph`) — deferred to v1.5.
- **Option A (monolithic builder)** — rejected; lazy embeddings conflict with cross-domain resolution. See `sdd/proposals/graphindex.proposal.md`.
- **Option C (plugin event-bus architecture)** — rejected; async coordination overhead not justified at this scale.

---

## 2. Architectural Design

### Overview

**Option B — Pipeline of stages with eager embeddings, FAISS hot + ArangoDB persistent.**

The build decomposes into six explicit stages, each consuming the output of the previous via Pydantic-validated contracts:

1. **Extract** — two parallel paths emit `UniversalNode` / `UniversalEdge` records.
   - *Code path*: tree-sitter parses source files → `Module`, `Class`, `Function`, `Rationale` nodes.
   - *Loader path*: `ai-parrot-loaders` → optional PageIndex for hierarchical content → `Section` / `Document` nodes.
   - *SKILL.md path*: frontmatter-derived `Skill` nodes.
2. **Embed** — batch embedding via `parrot.embeddings.EmbeddingModel` → FAISS (hot) + pgvector (persistent).
3. **Assemble** — `rustworkx.PyDiGraph` built in-process; node payloads are IDs + metadata only.
4. **Resolve cross-domain** — Level 1 cosine-similarity pass adds `mentions` edges with `provenance="inferred"`, `confidence=sim`.
5. **Persist** — `OntologyGraphStore.upsert_nodes` / `create_edges` → ArangoDB; embeddings → pgvector.
6. **Analyze + Report** — centrality, surprising connections, suggested questions → `GRAPH_REPORT.md`.

The toolkit reads from rustworkx + FAISS for hot queries, ArangoDB for cold-start hydration.

### Component Diagram

```
┌─────────────────────── GraphIndex Pipeline (per tenant) ───────────────────────┐
│                                                                                 │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐                     │
│  │ CodeExtractor │  │LoaderExtractor   │  │SkillExtractor │   ← Stage 1        │
│  │ (tree-sitter) │  │(loaders+PageIdx) │  │ (SKILL.md)    │                     │
│  └──────┬───────┘  └────────┬─────────┘  └──────┬────────┘                     │
│         │    UniversalNode   │    / UniversalEdge │                              │
│         └────────────┬───────┘───────────────────┘                              │
│                      ▼                                                          │
│              ┌───────────────┐                                                  │
│              │  EmbedStage   │  ← Stage 2 (parrot.embeddings.EmbeddingModel)    │
│              │  FAISS+pgvec  │                                                  │
│              └──────┬────────┘                                                  │
│                     ▼                                                           │
│              ┌───────────────┐                                                  │
│              │ AssembleStage │  ← Stage 3 (rustworkx PyDiGraph)                 │
│              └──────┬────────┘                                                  │
│                     ▼                                                           │
│              ┌───────────────┐                                                  │
│              │ResolveStage   │  ← Stage 4 (cross-domain cosine threshold)       │
│              └──────┬────────┘                                                  │
│                     ▼                                                           │
│              ┌───────────────┐                                                  │
│              │ PersistStage  │  ← Stage 5 (OntologyGraphStore + pgvector)       │
│              └──────┬────────┘                                                  │
│                     ▼                                                           │
│              ┌───────────────┐                                                  │
│              │AnalyzeStage  │  ← Stage 6 (centrality + GRAPH_REPORT.md)         │
│              └──────┬────────┘                                                  │
│                     ▼                                                           │
│         ┌─────────────────────┐    ┌──────────────────┐                         │
│         │ GraphIndexToolkit   │    │ GRAPH_REPORT.md   │                        │
│         │ (agent-facing tools)│    │ → KNOWLEDGE_LAYER │                        │
│         └─────────────────────┘    └──────────────────┘                         │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OntologyGraphStore` | uses | Persistence backend — `upsert_nodes`, `create_edges`, `get_all_nodes`, `soft_delete_nodes`. Consumed unchanged. [F001] |
| `TenantContext` / `MergedOntology` | uses | Tenant isolation. Extended with universal meta-ontology definition (additive). [F002] |
| `EntityDef` / `RelationDef` | extends | New entity and relation definitions for graph-index node/edge kinds. [F002] |
| `build_page_index` / `md_to_tree` | uses | Tree builders for hierarchical content in loader path. Requires `PageIndexLLMAdapter`. [F003] |
| `PageIndexNode` | uses | Node identity (`node_id`) becomes GraphIndex section identity. [F003] |
| `EmbeddingModel` / `EmbeddingRegistry` | uses | Stage 2 embedding computation. `SentenceTransformerModel` for HuggingFace models. [F011] |
| `KNOWLEDGE_LAYER` / `PromptBuilder` | uses | `GRAPH_REPORT.md` injected via `{"knowledge_content": text}`. [F004] |
| `AbstractToolkit` | extends | `GraphIndexToolkit` base class — public async methods auto-discovered as tools. [F005] |
| `AbstractClient` | uses | Optional LLM calls in `explain()` method and optional report polish. Uses `ask()` / `complete()`. [F006] |
| `AbstractLoader` / `parrot_loaders` | uses | Content acquisition — 24+ loaders for all non-code formats. Output: `List[Document]`. [F007] |
| `pyproject.toml` | extends | New `[graphindex]` extra: `rustworkx`, `tree-sitter`, `tree-sitter-languages`, `pathspec`. [F009] |

### Data Models

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class Provenance(str, Enum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"

class NodeKind(str, Enum):
    DOCUMENT = "document"
    SECTION = "section"
    SYMBOL = "symbol"
    CONCEPT = "concept"
    RATIONALE = "rationale"
    SKILL = "skill"

class EdgeKind(str, Enum):
    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"

class UniversalNode(BaseModel):
    node_id: str
    kind: NodeKind
    title: str
    source_uri: str
    content_ref: Optional[str] = None
    summary: Optional[str] = None
    embedding_ref: Optional[str] = None
    domain_tags: dict = Field(default_factory=dict)
    parent_id: Optional[str] = None
    provenance: Provenance = Provenance.EXTRACTED

class UniversalEdge(BaseModel):
    source_id: str
    target_id: str
    kind: EdgeKind
    provenance: Provenance = Provenance.EXTRACTED
    confidence: Optional[float] = None  # only when provenance == INFERRED
```

### New Public Interfaces

```python
# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit):
    """Agent-facing graph index tools."""

    async def find_node(self, query: str) -> list[dict]: ...
    async def find_references(self, node_id: str) -> list[dict]: ...
    async def get_neighborhood(self, node_id: str, depth: int = 2) -> dict: ...
    async def traverse(self, from_id: str, relation: str, to_kind: str | None = None) -> list[dict]: ...
    async def search_hybrid(self, query: str, top_k: int = 10) -> list[dict]: ...
    async def find_central_nodes(self, top_k: int = 10, metric: str = "betweenness") -> list[dict]: ...
    async def shortest_path(self, from_id: str, to_id: str) -> list[dict]: ...
    async def explain(self, node_id: str) -> str: ...
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
class GraphIndexBuilder:
    """Pipeline orchestrator for the 6-stage build."""

    async def build(self, sources: list[SourceConfig], ctx: TenantContext) -> BuildResult: ...
    async def ingest_document(self, uri: str, ctx: TenantContext) -> IngestResult: ...
    async def regenerate_report(self, ctx: TenantContext) -> Path: ...
```

---

## 3. Module Breakdown

### Module 1: Core Schema (`graph-index-core`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py`
- **Responsibility**: `UniversalNode`, `UniversalEdge`, `Provenance`, `NodeKind`, `EdgeKind` enums, `SourceConfig`, `BuildResult`, `IngestResult` models. Universal meta-ontology definition (YAML or programmatic) that extends the existing ontology system with 6 entity types and 5 relation types.
- **Depends on**: `parrot.knowledge.ontology.schema` (EntityDef, RelationDef, MergedOntology)

### Module 2: Code Extractor (`graph-index-extractors-code`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`
- **Responsibility**: tree-sitter-based extraction for Python (v1). Emits `Module`, `Class`, `Function` nodes plus `Rationale` nodes for docstrings and tagged comments (`NOTE`, `WHY`, `HACK`, `TODO`, `FIXME`, `XXX`). Edges: `contains`, `defines`, `imports`, `calls`, `explains`.
- **Depends on**: Module 1, `tree-sitter`, `tree-sitter-languages`

### Module 3: Loader-Based Extractor (`graph-index-extractors-loader`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py`
- **Responsibility**: Accepts any `ai-parrot-loaders` loader instance. Routes hierarchical content (PDF, MD, DOCX with headings, ebook) through `build_page_index` / `md_to_tree` → `Section` nodes. Flat content (audio/video transcript, plain web) → single `Document` node. Requires `PageIndexLLMAdapter` for hierarchical path.
- **Depends on**: Module 1, `parrot_loaders`, `parrot.pageindex` (build_page_index, md_to_tree, PageIndexLLMAdapter)

### Module 4: SKILL.md Extractor (`graph-index-extractors-skill`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/skill.py`
- **Responsibility**: Emits `Skill` nodes from `SKILL.md` files with frontmatter-derived `domain_tags`.
- **Depends on**: Module 1

### Module 5: Embedding Stage (`graph-index-embeddings`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py`
- **Responsibility**: Batch embedding via `EmbeddingModel.encode()` from `parrot.embeddings`. Populates `embedding_ref` on each node. Writes to FAISS (in-memory hot index) and pgvector (persistent). Uses `EmbeddingRegistry` for model caching.
- **Depends on**: Module 1, `parrot.embeddings` (EmbeddingModel, EmbeddingRegistry)

### Module 6: Graph Assembly (`graph-index-assembly`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py`
- **Responsibility**: Builds `rustworkx.PyDiGraph` from `UniversalNode` / `UniversalEdge` streams. Node payloads are IDs + metadata only; source bodies referenced via `content_ref`.
- **Depends on**: Module 1, `rustworkx`

### Module 7: Cross-Domain Resolution (`graph-index-resolution`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/resolve.py`
- **Responsibility**: Level 1 embedding-threshold pass. For each pair of nodes from different extractors, computes cosine similarity from FAISS. If `sim > τ`, emits `mentions` edge with `provenance="inferred"`, `confidence=sim`. Threshold τ configurable per kind-pair.
- **Depends on**: Module 1, Module 5 (FAISS index), Module 6 (assembled graph)

### Module 8: Persistence (`graph-index-persistence`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py`
- **Responsibility**: Writes to ArangoDB via `OntologyGraphStore.upsert_nodes` / `create_edges`. Writes embeddings to pgvector. Supports atomic per-document replacement for incremental refresh (soft-delete slice → re-upsert within ArangoDB transaction).
- **Depends on**: Module 1, `parrot.knowledge.ontology.graph_store.OntologyGraphStore`

### Module 9: Analytics + Report (`graph-index-analytics`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`
- **Responsibility**: Computes `rustworkx.betweenness_centrality` and `eigenvector_centrality` for god-nodes. Ranks cross-domain `mentions` edges by confidence. Generates deterministic `GRAPH_REPORT.md` from templates. Optional `--llm-polish` flag (v1.5).
- **Depends on**: Module 1, Module 6 (rustworkx graph), Module 7 (resolved edges)

### Module 10: Pipeline Builder (`graph-index-builder`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
- **Responsibility**: `GraphIndexBuilder` orchestrates all 6 stages. Provides `build()` for full reindex and `ingest_document()` for incremental refresh. `.graphindexignore` support via `pathspec`.
- **Depends on**: Modules 2-9

### Module 11: GraphIndex Toolkit (`graph-index-toolkit`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
- **Responsibility**: `GraphIndexToolkit(AbstractToolkit)` exposing 8 agent-facing methods. Reads from rustworkx + FAISS for hot queries. Cold-start hydration from ArangoDB.
- **Depends on**: Module 1, Module 6, Module 5, `parrot.tools.toolkit.AbstractToolkit`

### Module 12: Flowtask Integration (`graph-index-flowtask`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py`
- **Responsibility**: Flowtask component for batch reindex. Wraps `GraphIndexBuilder.build()`.
- **Depends on**: Module 10, external `flowtask` package Component contract

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_universal_node_validation` | 1 | UniversalNode Pydantic validation, defaults, provenance constraints |
| `test_universal_edge_confidence_rule` | 1 | confidence must be set iff provenance == INFERRED |
| `test_meta_ontology_definition` | 1 | Ontology YAML/programmatic definition produces correct EntityDef/RelationDef |
| `test_code_extractor_python_module` | 2 | Parses a simple Python file → Module, Class, Function nodes + edges |
| `test_code_extractor_rationale` | 2 | Extracts docstrings + tagged comments as Rationale nodes with explains edges |
| `test_code_extractor_parse_error` | 2 | Handles syntax errors gracefully (domain_tags={"parse_error": true}) |
| `test_loader_extractor_hierarchical` | 3 | PDF/MD content routes through PageIndex → Section nodes |
| `test_loader_extractor_flat` | 3 | Audio transcript → single Document node with flat tag |
| `test_loader_extractor_failure` | 3 | Loader error logged + skipped, pipeline continues |
| `test_skill_extractor` | 4 | SKILL.md → Skill node with frontmatter domain_tags |
| `test_embed_stage_batch` | 5 | Batch embedding produces FAISS index + pgvector entries |
| `test_embed_stage_failure` | 5 | Embedding failure → node persisted with embedding_ref=null |
| `test_assemble_graph` | 6 | UniversalNode/Edge stream → rustworkx PyDiGraph with correct topology |
| `test_resolve_cross_domain` | 7 | High-similarity cross-extractor pair → mentions edge with confidence |
| `test_resolve_threshold` | 7 | Below-threshold pair → no edge |
| `test_persist_upsert` | 8 | Nodes written to ArangoDB via OntologyGraphStore |
| `test_persist_incremental` | 8 | Soft-delete old slice + re-upsert atomically |
| `test_analytics_centrality` | 9 | Betweenness centrality identifies expected hub nodes |
| `test_report_generation` | 9 | GRAPH_REPORT.md generated with expected sections |
| `test_builder_full_pipeline` | 10 | End-to-end build with mock sources → graph + report |
| `test_builder_incremental` | 10 | ingest_document replaces one document's slice |
| `test_graphindexignore` | 10 | .graphindexignore patterns exclude files |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_pipeline_arango` | Full build with real ArangoDB (tenant-isolated) — nodes and edges persisted correctly |
| `test_toolkit_find_node` | GraphIndexToolkit.find_node returns correct results from hydrated graph |
| `test_toolkit_hybrid_search` | search_hybrid combines structural + embedding results |
| `test_toolkit_shortest_path` | shortest_path returns correct traversal |
| `test_report_knowledge_layer` | GRAPH_REPORT.md text injected via PromptBuilder.build() with knowledge_content |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_python_source() -> str:
    """Small Python file with module, class, function, docstring, and tagged comments."""
    ...

@pytest.fixture
def sample_markdown_doc() -> str:
    """Markdown document with heading hierarchy for PageIndex tree building."""
    ...

@pytest.fixture
def sample_skill_md() -> str:
    """SKILL.md file with frontmatter metadata."""
    ...

@pytest.fixture
def mock_tenant_context() -> TenantContext:
    """TenantContext with test arango_db, pgvector_schema, tenant_id, and a MergedOntology
    containing the universal meta-ontology entities and relations."""
    ...

@pytest.fixture
def mock_embedding_model():
    """Mock EmbeddingModel that returns deterministic vectors for testing."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] Universal node/edge schema validated with Pydantic; provenance + confidence constraints enforced
- [ ] Code extractor parses Python files via tree-sitter → Module/Class/Function/Rationale nodes
- [ ] Tagged comments (NOTE/WHY/HACK/TODO/FIXME/XXX) + docstrings extracted as Rationale nodes
- [ ] Loader extractor routes hierarchical content through PageIndex → Section nodes
- [ ] Loader extractor handles flat content → single Document node
- [ ] SKILL.md extractor emits Skill nodes with frontmatter domain_tags
- [ ] Embedding stage uses `parrot.embeddings.EmbeddingModel` (HuggingFace `SentenceTransformerModel`)
- [ ] FAISS hot index built at embed time; pgvector populated in same pass
- [ ] rustworkx `PyDiGraph` assembled from node/edge streams
- [ ] Cross-domain resolution generates `mentions` edges with `provenance="inferred"` and `confidence` score
- [ ] ArangoDB persistence via `OntologyGraphStore.upsert_nodes` / `create_edges` — tenant isolated
- [ ] Incremental refresh: soft-delete document slice + re-upsert atomically
- [ ] `GRAPH_REPORT.md` generated deterministically with god-nodes, surprising connections, suggested questions
- [ ] Report injectable via `PromptBuilder.build({"knowledge_content": report_text})`
- [ ] `GraphIndexToolkit` exposes all 8 v1 methods as auto-discovered tools
- [ ] `.graphindexignore` support via `pathspec`
- [ ] New `[graphindex]` extra in `pyproject.toml`: `rustworkx`, `tree-sitter`, `tree-sitter-languages`, `pathspec`
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/ -v`
- [ ] All integration tests pass with real ArangoDB
- [ ] No breaking changes to existing `OntologyGraphStore`, `PageIndex`, `parrot.embeddings`, or `PromptBuilder`
- [ ] Async-first, type-hinted, Pydantic-validated, Google-style docstrings throughout

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references verified via `/sdd-proposal` research agents (12 findings at `sdd/state/FEAT-187/findings/`).

### Verified Imports

```python
# Ontology persistence — F001
from parrot.knowledge.ontology.graph_store import OntologyGraphStore, UpsertResult
# verified: packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py exports OntologyGraphStore

# Ontology schema — F002
from parrot.knowledge.ontology.schema import (
    TenantContext,       # 4 fields: tenant_id, arango_db, pgvector_schema, ontology
    MergedOntology,      # entities: dict[str, EntityDef], relations: dict[str, RelationDef]
    EntityDef,           # collection, key_field, properties, vectorize, extend
    RelationDef,         # from_entity (alias "from"), to_entity (alias "to"), edge_collection
)
# verified: packages/ai-parrot/src/parrot/knowledge/ontology/schema.py

# PageIndex — F003
from parrot.pageindex import (
    build_page_index,      # async (doc, adapter, options?) -> dict
    md_to_tree,            # async (md_text, adapter, options?, doc_name?) -> dict
    PageIndexLLMAdapter,   # required second arg for both tree builders
    PageIndexNode,         # title, node_id, start_index, end_index, summary, text, nodes
)
# verified: packages/ai-parrot/src/parrot/pageindex/__init__.py

# Prompt system — F004
from parrot.bots.prompts.layers import KNOWLEDGE_LAYER, PromptLayer, LayerPriority
from parrot.bots.prompts.builder import PromptBuilder
# verified: packages/ai-parrot/src/parrot/bots/prompts/layers.py:181

# Toolkit base — F005
from parrot.tools.toolkit import AbstractToolkit
# verified: packages/ai-parrot/src/parrot/tools/toolkit.py:191

# LLM client (for explain() and optional report polish) — F006
from parrot.clients.base import AbstractClient
# verified: packages/ai-parrot/src/parrot/clients/base.py:242

# Embedding infrastructure — F011
from parrot.embeddings.base import EmbeddingModel
from parrot.embeddings.registry import EmbeddingRegistry
from parrot.embeddings.huggingface import SentenceTransformerModel
# verified: packages/ai-parrot/src/parrot/embeddings/

# Loaders — F007
# from parrot_loaders import <specific loader>
# verified: packages/ai-parrot-loaders/

…(truncated)…
