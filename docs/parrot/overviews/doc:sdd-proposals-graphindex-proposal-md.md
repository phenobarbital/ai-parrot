---
type: Wiki Overview
title: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
id: doc:sdd-proposals-graphindex-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Original brainstorm/proposal authored by Jesús Lara on 2026-05-19, exploring
  three architectural options for a structured knowledge graph layer that unifies
  code, documentation, and skill files into a single navigable surface for ai-parrot
  agents.
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
- concept: mod:parrot.clients
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
- concept: mod:parrot.knowledge
  rel: mentions
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.ontology
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot_tools.graphindex
  rel: mentions
---

---
id: FEAT-187
title: GraphIndex — Structured Knowledge Graph Indexing
slug: graphindex
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-19
  summary_oneline: GraphIndex — structured knowledge graph indexing unifying code, docs, and skills via pipeline-of-stages build
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-187/
created: 2026-05-19
updated: 2026-05-19
---

# FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/graphindex.proposal.md` (original brainstorm by Jesús Lara)
> **Audit**: [`sdd/state/FEAT-187/`](../state/FEAT-187/)

---

## 0. Origin

Original brainstorm/proposal authored by Jesús Lara on 2026-05-19, exploring three architectural options for a structured knowledge graph layer that unifies code, documentation, and skill files into a single navigable surface for ai-parrot agents.

> ai-parrot agents currently rely on three relatively flat retrieval surfaces: PageIndex for hierarchical PDF/Markdown trees, vector stores for embedding similarity, and OntologyGraphStore for tenant-isolated ArangoDB graphs. What is missing is a structured-knowledge graph layer that unifies these into a single navigable surface across source code, structured documentation, and skill files.

**Initial signals**:
- Verbs: "unifies", "indexes", "traverses" → new capability / enrichment
- Named entities: PageIndex, OntologyGraphStore, tree-sitter, rustworkx, FAISS, ArangoDB, ai-parrot-loaders
- Components: `parrot.knowledge`, `parrot.pageindex`, `parrot.embeddings`, `parrot.tools`, `parrot.bots.prompts`
- Acceptance criteria provided: yes (detailed decision table, 8 toolkit methods, 6-stage pipeline)

---

## 1. Synthesis Summary

GraphIndex is a new module at `parrot.knowledge.graphindex` that builds a structured knowledge graph by extracting entities and relations from multiple source types (Python code via tree-sitter, documents via ai-parrot-loaders + PageIndex, SKILL.md files), computing embeddings via `parrot.embeddings.EmbeddingModel`, assembling a rustworkx in-memory graph, resolving cross-domain edges by cosine similarity, persisting to ArangoDB via `OntologyGraphStore`, and generating a deterministic `GRAPH_REPORT.md` that injects into the agent's system prompt via the existing `KNOWLEDGE_LAYER`. An agent-facing `GraphIndexToolkit` (in `ai-parrot-tools`) exposes graph traversal, hybrid search, centrality, and path queries. All 9 integration points have been verified against the live codebase with high confidence. Five naming/reference corrections were identified and applied in this enriched version.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-187/findings/`. Each cites finding IDs.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | `OntologyGraphStore` | full file | Persistence backend — upsert_nodes, create_edges, get_all_nodes, soft_delete_nodes, execute_traversal, initialize_tenant | F001 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | `TenantContext`, `MergedOntology`, `EntityDef`, `RelationDef` | full file | Tenant isolation primitives — extended with universal meta-ontology definition | F002 |
| 3 | `packages/ai-parrot/src/parrot/pageindex/__init__.py` | `build_page_index`, `md_to_tree` | full file | Tree builders for hierarchical content (PDF, Markdown) — consumed by loader-based extractor | F003 |
| 4 | `packages/ai-parrot/src/parrot/pageindex/schemas.py` | `PageIndexNode`, `TreeSearchResult` | full file | Node schema with node_id, start_index, end_index, summary — becomes GraphIndex section identity | F003 |
| 5 | `packages/ai-parrot/src/parrot/bots/prompts/layers.py` | `KNOWLEDGE_LAYER`, `PromptLayer` | L181-189 | GRAPH_REPORT.md injection at priority 30 via `knowledge_content` context key | F004 |
| 6 | `packages/ai-parrot/src/parrot/bots/prompts/builder.py` | `PromptBuilder` | full file | Two-phase render with `build(context)` — caller passes `{"knowledge_content": report_text}` | F004 |
| 7 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit` | L191+ | Base class for GraphIndexToolkit — auto-discovers public async methods as tools | F005 |
| 8 | `packages/ai-parrot/src/parrot/embeddings/base.py` | `EmbeddingModel` | full file | ABC for Stage 2 (Embed) — `encode(texts) -> np.ndarray` | F011 |
| 9 | `packages/ai-parrot/src/parrot/embeddings/registry.py` | `EmbeddingRegistry` | full file | Singleton cache with LRU eviction, Matryoshka dimension awareness | F011 |
| 10 | `packages/ai-parrot/src/parrot/embeddings/huggingface.py` | `SentenceTransformerModel` | full file | HuggingFace provider — aligns with user's embedding model choice | F011 |
| 11 | `packages/ai-parrot/src/parrot/clients/base.py` | `AbstractClient` | full file | LLM calls for summaries/verification — use `ask()` or `complete()` | F006 |
| 12 | `packages/ai-parrot-loaders/` | `AbstractLoader`, `parrot_loaders` | package | Content acquisition — 24+ loaders for all mentioned formats | F007 |
| 13 | `packages/ai-parrot-tools/` | toolkit pattern | package | 40+ existing toolkits — GraphIndexToolkit follows same pattern | F012 |

### 2.2 Constraints Discovered

- **Embedding infrastructure is independent from LLM clients.** `parrot.embeddings.EmbeddingModel` is a separate ABC from `AbstractClient`. The Embed stage must use `EmbeddingModel.encode()` (not `AbstractClient`). Three providers exist: HuggingFace (`SentenceTransformerModel`), OpenAI, Google. The `EmbeddingRegistry` provides singleton caching. *Evidence*: F006, F011

- **Schema type names differ from proposal.** The ontology schema uses `MergedOntology` (not `Ontology`), `EntityDef` (not `Entity`), `RelationDef` (not `Relation`). The universal meta-ontology definition must use these exact types. *Evidence*: F002

- **TenantContext includes pgvector_schema.** `TenantContext` has 4 fields: `tenant_id`, `arango_db`, `pgvector_schema`, `ontology: MergedOntology`. The `pgvector_schema` field can be leveraged for embedding table namespace isolation. *Evidence*: F002

- **PageIndex functions require PageIndexLLMAdapter.** Both `build_page_index` and `md_to_tree` take a `PageIndexLLMAdapter` as their second argument. The loader-based extractor must instantiate one when routing hierarchical content through PageIndex. *Evidence*: F003

- **AbstractToolkit discovers tools by introspection.** Public async methods automatically become tools — no `@tool` decorator needed on toolkit methods. In `ai-parrot-tools`, the convention is `@tool_schema(PydanticInputModel)` for input validation. *Evidence*: F005, F012

- **Flowtask Component is external.** The `Component` base class lives in the external `flowtask` package, not in ai-parrot. Components are loaded dynamically via `flowtask.components.<Name>`. The GraphIndex Flowtask component must follow the external package's contract. *Evidence*: F010

- **OntologyGraphStore uses soft-delete with _active flag.** `upsert_nodes` sets `_active: true`; `get_all_nodes` filters by `_active != false`; `soft_delete_nodes` uses `_key` values (not `key_field`). Incremental refresh should use soft-delete + re-upsert for audit trail. *Evidence*: F001

- **faiss-cpu is already a core dependency.** Present in both core `dependencies` and the `[embeddings]` extra. No additional FAISS dependency declaration needed for graphindex. *Evidence*: F009

- **Heavy recent ontology development.** 30+ commits in the last 30 days on `parrot/knowledge/ontology/`: entity extraction (FEAT-158), concept catalog, schema overlay, concept embedding pipeline. GraphIndex should avoid conflicting with these active areas. *Evidence*: F008

### 2.3 Recent History (Relevant)

| Area | Recent Activity | Evidence |
|------|----------------|----------|
| `parrot/knowledge/ontology/` | 30+ commits: entity extraction, concept catalog, schema overlay, authorization, tool dispatcher | F008 |
| `parrot/pageindex/` | No recent changes | F003 |
| `parrot/embeddings/` | Matryoshka support (FEAT-150), EmbeddingRegistry with LRU | F011 |
| `parrot/bots/prompts/` | CacheableSegment support (FEAT-181) | F004 |

---

## 3. Probable Scope *(enrichment mode)*

### What's New

- **`parrot.knowledge.graphindex`** — new module containing: universal node/edge schema, code extractor (tree-sitter), loader-based extractor, SKILL.md adapter, pipeline builder (6 stages), cross-domain resolver, analytics + report generator
- **`parrot_tools.graphindex.GraphIndexToolkit`** — agent-facing toolkit with 8 methods (v1) + 1 (v1.5)
- **`[graphindex]` extra in pyproject.toml** — `rustworkx`, `tree-sitter`, `tree-sitter-languages`, `pathspec`
- **Flowtask Component** — batch reindex component (in external flowtask package or as ai-parrot-tools integration)
- **`GRAPH_REPORT.md`** — deterministic report injected via KNOWLEDGE_LAYER

### What Changes

- **`parrot.knowledge.ontology.schema`** — new `MergedOntology` definition for the universal meta-ontology (6 entity types: `document`, `section`, `symbol`, `concept`, `rationale`, `skill`; 5 relation types: `contains`, `references`, `defines`, `mentions`, `explains`). Additive only — existing ontology definitions unchanged. *Evidence*: F002
- **`packages/ai-parrot/pyproject.toml`** — new `[graphindex]` extra. *Evidence*: F009

### What's Untouched (Non-Goals)

- `parrot.pageindex` — consumed as-is, no source changes
- `parrot.bots.prompts` — consumed as-is, no source changes
- `parrot.embeddings` — consumed as-is, no source changes
- `parrot.clients` — consumed as-is for optional LLM calls
- `parrot_loaders` — consumed as-is, no source changes
- `OntologyGraphStore` implementation — consumed unchanged
- MCP server exposure — out of v1 scope

### Patterns to Follow

- **Toolkit pattern**: extend `AbstractToolkit`, expose public async methods, use `@tool_schema()` for input models (per 40+ existing toolkits). *Evidence*: F005, F012
- **Embedding pattern**: use `EmbeddingRegistry.get()` to obtain a cached `EmbeddingModel` instance, call `encode(texts)` for batch embedding. *Evidence*: F011
- **Ontology extension pattern**: define new `EntityDef` and `RelationDef` entries in a YAML ontology layer; `MergedOntology` merges them with existing tenant ontologies. *Evidence*: F002
- **Knowledge injection pattern**: `PromptBuilder.build({"knowledge_content": report_text})` → KNOWLEDGE_LAYER renders `<knowledge_context>` block. *Evidence*: F004
- **Loader consumption pattern**: `AbstractLoader.load(source) -> List[Document]` with `page_content` + `metadata` dict. *Evidence*: F007

### Integration Risks

- **Ontology schema conflicts**: Heavy concurrent development on `parrot.knowledge.ontology` (30+ recent commits). The universal meta-ontology addition is additive but must be tested against active features (entity extraction, concept catalog). *Evidence*: F008. *Mitigation*: additive-only changes, integration tests against existing tenants.
- **PageIndex LLM dependency**: The loader-based extractor for hierarchical content requires `PageIndexLLMAdapter`, which needs an LLM client. This adds latency to the Extract stage for hierarchical documents. *Mitigation*: make LLM summarization optional (fall back to first-N-chars summary). *Evidence*: F003
- **External Flowtask dependency**: Component base class is in the external `flowtask` package. Contract may change independently. *Evidence*: F010. *Mitigation*: decouple via adapter; verify contract during `/sdd-spec`.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | OntologyGraphStore provides all needed persistence methods | F001 | high | Direct read verification of all 6 methods |
| C2 | Schema types are MergedOntology/EntityDef/RelationDef (not Ontology/Entity/Relation) | F002 | high | Direct read of schema.py |
| C3 | TenantContext has pgvector_schema field useful for embedding storage | F002 | high | Direct read |
| C4 | PageIndex API matches expectations (build_page_index, md_to_tree) | F003 | high | Direct read of __init__.py |
| C5 | PageIndex requires PageIndexLLMAdapter for tree building | F003 | high | Function signature verification |
| C6 | KNOWLEDGE_LAYER injects at priority 30 via knowledge_content | F004 | high | Direct read, template matches |
| C7 | PromptBuilder.build() accepts knowledge_content in context dict | F004 | high | Direct read of builder.py |
| C8 | AbstractToolkit auto-discovers async methods as tools | F005 | high | Direct read of _generate_tools() |
| C9 | Embeddings use parrot.embeddings.EmbeddingModel, not AbstractClient | F006, F011 | high | AbstractClient has no embed(); EmbeddingModel ABC confirmed |
| C10 | HuggingFace SentenceTransformerModel available for embedding | F011 | high | Direct read |
| C11 | ai-parrot-loaders has 24+ loaders covering all mentioned formats | F007 | high | Package listing |
| C12 | graphindex namespace is clean (no existing references) | F008 | high | grep returned zero matches |
| C13 | New [graphindex] extra needed for rustworkx, tree-sitter, pathspec | F009 | high | grep of pyproject.toml |
| C14 | faiss-cpu already available (core dependency + embeddings extra) | F009 | high | Direct read |
| C15 | Flowtask Component is external — contract needs verification | F010 | medium | Dynamic import confirmed; exact interface unverified |
| C16 | 40+ existing toolkits provide pattern for GraphIndexToolkit | F012 | high | Package listing |
| C17 | Loader output is List[Document] with page_content + metadata | F007 | high | AbstractLoader interface read |
| C18 | No is_hierarchical() on loaders — detection is application-level | F007 | medium | Absence confirmed; design decision needed |

Distribution: **15** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal/research phase)

- [x] **Embedding model** — *Resolved*: User specified "using huggingfaces embedding models". The existing `SentenceTransformerModel` provider in `parrot.embeddings` with the 50KB model catalog is the correct integration point. *Resolves*: C9, C10
- [x] **AbstractClient.ask signature** — *Resolved*: `ask(prompt, model, max_tokens, temperature, ...) -> MessageResponse`. Use `complete()` for simple text extraction. *Resolves*: C9
- [x] **TenantContext field set** — *Resolved*: 4 fields: `tenant_id`, `arango_db`, `pgvector_schema`, `ontology: MergedOntology`. *Resolves*: C2, C3
- [x] **AbstractToolkit mechanism** — *Resolved*: auto-discovers public async methods via introspection. Use `@tool_schema(InputModel)` in ai-parrot-tools. *Resolves*: C8
- [x] **Naming** — *Resolved*: User confirmed `graphindex` (flat). Module path: `parrot.knowledge.graphindex`.
- [x] **Rationale extraction scope** — *Resolved*: Tagged comments only (NOTE/WHY/HACK/TODO/FIXME/XXX) + docstrings by default; `--all-comments` opt-in.
- [x] **GRAPH_REPORT.md generation** — *Resolved*: Deterministic in v1 (centrality + top-K mentions + templated questions); LLM polish opt-in in v1.5.

### Unresolved (defer to spec / implementation)

- [ ] **Cross-domain threshold τ** — calibration per kind-pair. Initial: one global τ in v1, per-pair overrides v1.1. — *Owner*: Jesús
  *Plausible answers*: a) single τ=0.7 globally · b) τ per kind-pair from calibration · c) learned threshold
- [ ] **Flowtask Component contract** — exact base class and registration mechanism in external `flowtask` package. — *Owner*: Jesús
  *Blocks claims*: C15
  *Plausible answers*: a) extend `flowtask.components.Component` · b) register via entry point · c) adapter wrapper
- [ ] **Loader hierarchical detection** — how the LoaderBasedExtractor detects hierarchical vs flat content. — *Owner*: Jesús
  *Blocks claims*: C18
  *Plausible answers*: a) static mapping per loader type · b) probe output for heading structure · c) metadata flag
- [ ] **Body storage strategy** — where source bodies live (ArangoDB, Redis, sqlite sidecar). Affects `content_ref` resolution latency. — *Owner*: Jesús
- [ ] **Soft-delete vs hard-delete on incremental refresh** — Recommend soft-delete (OntologyGraphStore already supports `_active` flag pattern). — *Owner*: Jesús
- [ ] **Suggested-questions template structure** — template parameterization for deterministic report. — *Owner*: Jesús

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-187`** — *Rationale*: localization is high-confidence across all 9 integration points (15 of 18 claims at high confidence). The architectural recommendation (Option B — pipeline of stages) is well-justified. All critical code references verified. Corrections are naming fixes only — no architectural impact. Ready for spec decomposition.

### Alternatives

- **`/sdd-brainstorm FEAT-187`** — if you want to re-evaluate the three architectural options with the corrected code context (unlikely needed — Option B analysis is thorough).
- **`/sdd-task FEAT-187`** — not recommended; this is a large multi-module feature requiring spec-level decomposition first.
- **Manual review** — research was complete (not truncated); review `sdd/state/FEAT-187/` for full audit trail.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-187/state.json` |
| Source (raw) | `sdd/state/FEAT-187/source.md` |
| Research plan | `sdd/state/FEAT-187/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-187/findings/F001-*.md` through `F012-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-187/synthesis.json` |

**Budget consumed**:
- Files read: ~15 / 40
- Grep calls: ~16 / 25
- Git calls: ~3 / 10
- Wall time: ~270s / 300s
- Truncated: **no**

**Mode determination**: forced `enrichment` (file source with detailed architectural proposal).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | manual (no template — inline synthesis) |
| Plan prompt | manual (16-query research plan) |
| Research agents | 5 parallel agents covering 16 queries |
| Operator | Claude Opus 4.6 for Jesús Lara |

---

## Appendix A: Verified Codebase References (Corrected)

### Corrected Imports

```python
from parrot.knowledge.ontology.graph_store import OntologyGraphStore, UpsertResult
from parrot.knowledge.ontology.schema import (
    TenantContext,       # tenant_id, arango_db, pgvector_schema, ontology
    MergedOntology,      # NOT "Ontology" — has entities, relations, traversal_patterns, layers
    EntityDef,           # NOT "Entity" — collection, key_field, properties, vectorize
    RelationDef,         # NOT "Relation" — from_entity, to_entity, edge_collection
)
from parrot.pageindex import (
    build_page_index, md_to_tree, PageIndexRetriever, PageIndexLLMAdapter,
    PageIndexNode, TreeSearchResult, TocItem,
)
from parrot.bots.prompts.layers import KNOWLEDGE_LAYER, PromptLayer, LayerPriority
from parrot.bots.prompts.builder import PromptBuilder
from parrot.tools import AbstractToolkit           # auto-discovers public async methods
from parrot.tools.decorators import tool           # for standalone functions only
from parrot.clients.base import AbstractClient     # ask(), complete() — NOT for embeddings
from parrot.embeddings.base import EmbeddingModel  # encode(texts) -> np.ndarray
from parrot.embeddings.registry import EmbeddingRegistry  # singleton cache
from parrot.embeddings.huggingface import SentenceTransformerModel  # HF provider
# ai-parrot-loaders:
#   from parrot_loaders import ...  (AbstractLoader._load -> List[Document])
```

### Corrected Key Attributes

- `TenantContext.arango_db` → `str`
- `TenantContext.pgvector_schema` → `str` (NEW — useful for embedding table namespace)
- `TenantContext.tenant_id` → `str`
- `TenantContext.ontology` → `MergedOntology` (NOT `Ontology`)
- `MergedOntology.entities` → `dict[str, EntityDef]`
- `MergedOntology.relations` → `dict[str, RelationDef]`
- `MergedOntology.get_entity_collections()` → `list[str]`
- `MergedOntology.get_edge_collections()` → `list[str]`
- `EntityDef.collection` → `str | None`
- `EntityDef.key_field` → `str | None`
- `RelationDef.edge_collection` → `str`
- `RelationDef.from_entity` → `str` (alias `"from"`)
- `RelationDef.to_entity` → `str` (alias `"to"`)

### Does NOT Exist (Anti-Hallucination) — Verified

- ~~`parrot.knowledge.graphindex`~~ — confirmed: zero grep matches [F008]
- ~~`parrot_tools.graphindex.GraphIndexToolkit`~~ — confirmed: does not exist [F012]
- ~~`tree-sitter`, `rustworkx`, `pathspec` in pyproject.toml~~ — confirmed: not declared [F009]
- ~~`AbstractClient.embed()`~~ — confirmed: no such method [F006]
- ~~`AbstractClient.completion()`~~ — confirmed: no such method; use `ask()` or `complete()` [F006]
- ~~`Ontology` class~~ — actual name is `MergedOntology` [F002]
- ~~`Entity` class~~ — actual name is `EntityDef` [F002]
- ~~`Relation` class~~ — actual name is `RelationDef` [F002]

---

## Appendix B: Original Proposal Content (Preserved)

The original proposal with three architectural options (A: Monolithic, B: Pipeline of stages, C: Plugin architecture) is preserved in the research state at `sdd/state/FEAT-187/source.md`. Option B (Pipeline of stages) remains the recommended approach. The full decision table, feature description, capability list, impact assessment, parallelism assessment, and open questions from the original are incorporated into this enriched version with all code references verified and corrected.
