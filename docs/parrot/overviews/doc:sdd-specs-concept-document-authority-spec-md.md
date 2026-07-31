---
type: Wiki Overview
title: 'Feature Specification: Concept-Document Authority Layer'
id: doc:sdd-specs-concept-document-authority-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Pure vector RAG over a corporate corpus produces high-confidence false positives
  because semantic similarity does not capture **document authority** within that
  corpus:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.core
  rel: mentions
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
- concept: mod:parrot.knowledge.ontology.entity_resolver
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tool_dispatcher
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Concept-Document Authority Layer

**Feature ID**: FEAT-159
**Date**: 2026-05-11
**Author**: Jesús Lara
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Pure vector RAG over a corporate corpus produces high-confidence false positives because semantic similarity does not capture **document authority** within that corpus:

- *"How do commissions work?"* → retrieves a critical memo titled *"Why our commissions are not working"* instead of the canonical Sales Commissions Policy.
- *"What is our PTO policy?"* → retrieves an FAQ that paraphrases the policy instead of the policy itself.
- *"Refund process?"* → retrieves a customer-service training deck instead of the operational SOP.

The error is **structural**: authority is not a property of *content*, it is a property of the document's role in the corpus, declared by the organization. Embeddings cannot recover this signal post-hoc, no matter how well-tuned the model.

PageIndex (`parrot/pageindex/retriever.py:11`) already does high-quality intra-document retrieval via LLM tree-search. What is missing is a **routing layer** that, for a given query, asserts *"the authoritative document(s) for this concept is/are X, Y — search inside THOSE PageIndex trees, not the whole corpus"*. This feature introduces that routing layer.

The error mode is structural; Options B (vector reranker with authority metadata) and C (LLM-as-router over a flat document catalog) both treat authority as something the system infers, so neither solves the *"commissions are not working" memo* class of failure. Option A — declared authority via curated graph edges — is the only approach that makes authority deterministic, cacheable, and auditable, so this spec commits to it.

### Goals

- Add `Document` and `Concept` as first-class ontology entities and `covers_topic` / `is_a` as ontology relations in a new YAML layer (`knowledge.ontology.yaml`-style file) that **extends** the base ontology.
- Introduce a **per-tenant authority file** at `{ontology_dir}/authority/{tenant_id}.yaml` carrying only `covers_topic` and `is_a` edges. Document/Concept *definitions* stay in tenant ontology files; edges live separately for cleaner git review.
- Add a new traversal pattern **`authoritative_doc_for_topic`** that uses FEAT-158's `entity_extraction` to resolve query terms to `Concept` IDs, walks `is_a` 0..3 levels for taxonomic recall, filters `covers_topic` edges by `authority="primary"` and `Document.is_current=true`, and dispatches the result to PageIndex via FEAT-158's `tool_call` post-action.
- Implement the **`hybrid_concept_match`** resolver strategy in `EntityResolver` (the strategy FEAT-158 declared but left at `NotImplementedError`). Algorithm: synonym/fuzzy exact match → vector top-K against a shared concepts namespace filtered by `tenant_id` → LLM tie-breaker on top-5. Returns a `list[str]` for multi-concept queries; multi-concept union semantics are realized in the traversal AQL.
- Add **`PageIndexToolkit.search_documents_scoped(tree_ids, query, include_tree_context=False)`** — a new tool method that runs PageIndex's existing `retriever.search()` + `retriever.retrieve()` against a *subset* of indexed trees. Zero duplication of PageIndex code.
- Build a **concept embedding pipeline** in `TenantOntologyManager.resolve()`: on each tenant resolve, compute `sha256(label + sorted(synonyms) + description)` per Concept, diff against stored hashes in `{ontology_dir}` cache, embed and upsert changed/new concepts into the **shared** PgVector namespace `concepts` with `tenant_id` metadata; delete removed concepts. Idempotent and fast.
- Extend `PgVectorStore.search()` and `PgVectorStore.add_documents()` with a generic **`metadata_filters: dict[str, Any] | None`** parameter that ANDs into the WHERE clause; concepts namespace passes `{"tenant_id": tenant_id}`. Reusable for any future row-level filter.
- Add the **4-level graceful degradation chain** to `OntologyRAGMixin.ontology_process` (per FEAT-158's refactored flow):
  1. `authority="primary"` traversal → tool_call to PageIndex → `state="ok"`, `context.source="graph:primary"`.
  2. Relax to `authority="secondary"` and retry → `context.source="graph:secondary"`.
  3. Vector RAG **filtered by `doc_type IN ('policy', 'manual')`** → `context.source="vector:filtered"`.
  4. Plain vector RAG → `context.source="vector:plain"`.
- Refactor `IntentRouterMixin._run_graph_pageindex` to drive PageIndex *through* the ontology rather than as a parallel cascade. Unscoped PageIndex remains as the **last** fallback for queries where no concept is modeled.

### Non-Goals (explicitly out of scope)

- Curation lifecycle for `covers_topic` edges (creation, merging, deprecation, stale-edge alerts, audit). *Owned by FEAT-topic-authority-operational.*
- New PageIndex tree builders or extractors. PageIndex's API surface is unchanged except for the additive `search_documents_scoped`.
- Replacing or competing with vector RAG. Vector remains the safety net (levels 3 and 4 of the degradation chain).
- A `Section` entity for sub-document granularity. *(Rejected in brainstorm — see proposals/concept-document-authority.brainstorm.md Open Questions resolution. Revisit when a real use case requires cross-section linking or section-level authority.)*
- Concept lifecycle UI. Concepts are added/edited/removed via YAML at v1.
- Bootstrap script that proposes `covers_topic` edges from existing documents. *(Rejected for v1 — YAML-only at FEAT-159; LLM auto-proposer belongs to FEAT-topic-authority-operational.)*
- LLM-based router over a flat document catalog (brainstorm Option C). Rejected: per-query LLM cost, non-determinism, and prompt size grows with corpus.
- Vector reranker with authority metadata (brainstorm Option B). Rejected: does not solve the structural problem; per-corpus tuning never converges.
- Multi-document **intersection** optimization (prefer a doc that covers *both* concepts in a multi-concept query). v1 uses union. Revisit if recall is poor.
- Re-ranking or merging strategy across PageIndex tree results beyond passing all `scoped_results` to the LLM with `{doc_type, version, authority}` labels.
- ETL changes for ingesting documents and writing `pageindex_tree_id` / `version` / `is_current` back into the graph. The ETL is the *consumer* of this contract; this spec defines the contract and end-to-end tests use fixtures that mimic ETL output.

---

## 2. Architectural Design

### Overview

Four cooperating pieces sit on top of FEAT-158's refactored ontology pipeline:

1. **A new YAML layer** declares `Document` and `Concept` entities, `covers_topic` and `is_a` relations, and one traversal pattern `authoritative_doc_for_topic`. The pattern uses FEAT-158's `entity_extraction` (resolver `hybrid_concept_match`) + `tool_call` (toolkit `PageIndexToolkit`, method `search_documents_scoped`) — zero new orchestration plumbing.
2. **`hybrid_concept_match` strategy** lands inside `EntityResolver` (Module 2 of FEAT-158). It returns a `list[str]` of resolved Concept `_id`s (multi-concept aware). Resolution path: synonym/fuzzy exact → vector top-K against shared `concepts` namespace filtered by `tenant_id` → LLM tie-breaker on top-5. Result cached by `(query_hash, ontology_version, tenant_id)`.
3. **`PageIndexToolkit.search_documents_scoped`** iterates a subset of `_indices` (existing dict at `pageindex_toolkit.py:63`) and calls the existing `retriever.search()` + `retriever.retrieve()` for each, returning merged `scoped_results`. The tool is invoked through FEAT-158's `ToolCallDispatcher` like any other tool — the dispatcher renders `tree_ids` via Jinja2 (`{{ graph.rows | map_attr('pageindex_tree_id') | json }}`) and forwards `_permission_context` for consistency (PageIndex itself does not need OAuth, but the toolkit honors the kwarg without complaint).
4. **The 4-level degradation chain** lives inside the refactored `ontology_process` (FEAT-158 Module 5). When `state="ok"` traversal returns empty (no concept matched OR no primary edge), the Mixin retries with `authority="secondary"`, then falls through to filtered vector, then plain vector. Each step tags `envelope.context.source` so the agent layer can disclose provenance.

The **concept embedding pipeline** runs inside `TenantOntologyManager.resolve()`. It is content-hash idempotent (sha256 of `label + sorted(synonyms) + description`) and writes into the shared `concepts` PgVector namespace with `tenant_id` metadata. A new generic `metadata_filters: dict | None` parameter on `PgVectorStore.search()` and `.add_documents()` powers row-level tenant filtering without per-tenant schemas.

`IntentRouterMixin._run_graph_pageindex` becomes a thin adapter: it calls `ontology_process` (already fixed in FEAT-158 to forward `user_context` + `tenant_id`), branches on `ContextEnvelope.state`, and falls back to the standalone `PageIndexRetriever.retrieve(prompt)` only when ontology returns `state="ok"` with empty context (i.e., no concept modeled).

### Component Diagram

```
User query
   │
   ▼
IntentRouterMixin._run_graph_pageindex            ── intent_router.py:615 (already refactored by FEAT-158)
   │  forwards user_context + tenant_id
   ▼
OntologyRAGMixin.ontology_process                  ── mixin.py:65 (refactored by FEAT-158; this feature adds degradation chain)
   │
   ├─► OntologyIntentResolver.resolve              ── intent.py:97 (existing)
   │     matches trigger_intents of authoritative_doc_for_topic
   │
   ├─► EntityResolver.extract_and_resolve          ── entity_resolver.py (FEAT-158)
   │     │
   │     └─► strategy: hybrid_concept_match        ── NEW in this feature
   │            │
   │            ├─ synonym/fuzzy exact (in-memory over ontology.concepts)
   │            ├─ vector top-K (PgVectorStore.search on "concepts" namespace,
   │            │                metadata_filters={"tenant_id": tenant_id})  ── NEW
   │            └─ LLM tie-breaker on top-5
   │     returns dict[rule_name -> list[concept_id]]  (multi-concept aware)
   │
   ├─► OntologyCache.build_key                     ── cache.py:43 (extended by FEAT-158 to include resolved_entities)
   │
   ├─► OntologyGraphStore.execute_traversal        ── graph_store.py:185 (existing)
   │     runs AQL: walk is_a 0..3, filter covers_topic.authority=='primary',
   │              Document.is_current==true, ORDER BY authority_score, effective_date;
   │              UNION across concept_id list for multi-concept queries
   │     returns list[{document_id, title, doc_type, version, pageindex_tree_id, ...}]
   │
   └─► Post-action: tool_call                      ── mixin.py refactor (FEAT-158)
        │
        └─► ToolCallDispatcher.dispatch            ── tool_dispatcher.py (FEAT-158)
              │  Jinja2 renders `tree_ids` from graph.rows via map_attr('pageindex_tree_id') | json
              │  ToolManager.get_tool("PageIndexToolkit.search_documents_scoped")
              │
              └─► PageIndexToolkit.search_documents_scoped(tree_ids, query, include_tree_context)   ── NEW (this feature)
                     │
                     └─► for each tree_id in tree_ids:
                            r = self._indices[tree_id]["retriever"]                                  ── pageindex_toolkit.py:63 (existing)
                            search_result = await r.search(query)                                    ── retriever.py:38
                            context      = await r.retrieve(query)                                   ── retriever.py:81
                     returns {"status": "ok", "scoped_results": [...]}

If traversal returns empty OR resolver returns []:
   degradation chain (inside ontology_process):
      1. relax authority -> "secondary", retry
      2. PgVectorStore.search with metadata_filters={"doc_type": ["policy","manual"]}  -> source="vector:filtered"
      3. plain vector RAG                                                              -> source="vector:plain"
   each step sets envelope.context.source accordingly.

Concept embedding pipeline (out-of-band, on tenant resolve):
   TenantOntologyManager.resolve(tenant_id)        ── tenant.py:74
      │
      └─► ConceptEmbeddingPipeline.sync(tenant_id, concepts)        ── NEW
              │
              ├─ compute sha256(label + sorted(synonyms) + description) per Concept
              ├─ diff against {ontology_dir}/.concept_hashes/{tenant_id}.json
              └─ PgVectorStore.add_documents(schema="...", table="concepts",
                                              documents=changed_concepts,
                                              metadata_filters={"tenant_id": tenant_id})  -- for upsert delete-and-insert
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/knowledge/ontology/defaults/base.ontology.yaml` | extends | New `Document` and `Concept` entity defs, `covers_topic` and `is_a` relation defs, `authoritative_doc_for_topic` traversal pattern. All optional — absence is backwards compatible. |
| `parrot/knowledge/ontology/parser.py` + `merger.py` | uses, unchanged | YAML is loaded through the existing parser/merger. No code changes — only new YAML content. Verified merge rules accept new entities/relations/patterns without modification (per `merger.py:26-130`). |
| `parrot/knowledge/ontology/tenant.py` (`TenantOntologyManager.resolve`) | extends | Calls `ConceptEmbeddingPipeline.sync()` after merge resolves. Pipeline is async and idempotent; failures log and do not block resolve. |
| `parrot/knowledge/ontology/entity_resolver.py` (FEAT-158) | extends | Replace `NotImplementedError` for `hybrid_concept_match` strategy with the actual implementation. Strategy signature unchanged — still returns `dict[rule_name, str | list[str]]`; this feature relaxes the value to `list[str]` for multi-concept rules. |
| `parrot/knowledge/ontology/mixin.py` (`OntologyRAGMixin.ontology_process`) | extends | After FEAT-158's refactor, wrap the traversal+tool_call block in the 4-level degradation chain. `ContextEnvelope.context.source` is set per level. Untouched paths from FEAT-158 (ambiguity, denial, auth_required, render_error) bypass the chain. |
| `parrot/tools/pageindex_toolkit.py` (`PageIndexToolkit`) | extends | New `search_documents_scoped` method, new `SearchScopedInput` pydantic model. Uses existing `_indices` dict and existing `PageIndexRetriever.search` + `.retrieve`. Zero duplication of PageIndex tree-search code. |
| `parrot/stores/postgres.py` (`PgVectorStore`) | extends | New `metadata_filters: dict[str, Any] \| None = None` parameter on `search()` and `add_documents()`. ANDs into the WHERE clause; `IN (…)` semantics when value is a list. Backwards compatible — default is no filter. |
| `parrot/bots/mixins/intent_router.py` (`_run_graph_pageindex`) | uses, unchanged | After FEAT-158's refactor, this method already forwards `user_context` + `tenant_id` to `ontology_process`. This feature only changes the **branch logic on `ContextEnvelope.state`** so unscoped PageIndex is the explicit last resort, not a parallel path. |
| `parrot/pageindex/retriever.py` (`PageIndexRetriever`) | uses, unchanged | `.search()` and `.retrieve()` are called as-is by `search_documents_scoped`. |
| `parrot/knowledge/ontology/schema.py` | uses, unchanged | `EntityExtractionRule`, `ToolCallSpec`, `ContextEnvelope` all defined by FEAT-158. No schema additions in this feature. |
| ETL pipeline (out of scope, consumer) | depends on | ETL must write `pageindex_tree_id`, bump `version`, set `is_current=true` on new versions and `false` on prior versions when re-indexing a document. End-to-end tests use fixtures, not real ETL. |

### Data Models

No Python schema additions in this feature. All entity and relation definitions are YAML, validated by FEAT-158's existing `EntityDef`/`RelationDef`/`TraversalPattern` models.

The YAML extension is reproduced below (lives at `parrot/knowledge/ontology/defaults/knowledge.ontology.yaml`):

```yaml
name: knowledge
extends: base
version: "1.0"

entities:
  Document:
    collection: documents
    source: confluence              # pluggable per tenant
    key_field: document_id
    properties:
      - document_id:       { type: string, required: true, unique: true }
      - title:             { type: string, required: true }
      - doc_type:          { type: string, enum: ["policy", "manual", "memo", "guide", "faq"] }
      - version:           { type: string }
      - effective_date:    { type: date }
      - is_current:        { type: boolean, default: true }
      - authority_score:   { type: float, default: 0.5, description: "0..1, tie-break weight when multiple primaries match" }
      - pageindex_tree_id: { type: string, description: "Opaque reference to a PageIndex tree (written by ETL on ingest)" }
      - language:          { type: string, default: "en" }
    vectorize:
      - title                       # ONLY title; chunks go via PageIndex

  Concept:
    collection: concepts
    key_field: concept_id
    properties:
      - concept_id:  { type: string, required: true, unique: true }
      - label:       { type: string, required: true }
      - synonyms:    { type: list }
      - description: { type: string }
      - domain:      { type: string, description: "Disambiguator: 'finance', 'hr', 'sales'" }
    vectorize:
      - label
      - description
      - synonyms

relations:
  covers_topic:
    from: Document
    to: Concept
    edge_collection: doc_covers_concept
    properties:
      - authority:   { type: string, enum: ["primary", "secondary", "mentions"], required: true }
      - confidence:  { type: float, default: 1.0 }
      - asserted_by: { type: string, description: "Curator id or 'auto:ner_v1'" }

  is_a:
    from: Concept
    to: Concept
    edge_collection: concept_is_a

traversal_patterns:
  authoritative_doc_for_topic:
    description: >
      Route topical queries through curated authority edges into PageIndex.
      Walks Concept taxonomy via is_a so sub-concepts are included; supports
      multi-concept queries via UNION over the resolved concept list.

    trigger_intents:
      - how does
      - how do
      - cómo funciona
      - cómo funcionan
      - what is the policy on
      - cuál es la política de
      - política de
      - explain
      - explícame

    entity_extraction:
      topic:
        type: Concept
        resolver: hybrid_concept_match
        scope: same_tenant
        ambiguity_strategy: rerank_by_authority
        required: true

    query_template: |
      LET concept_family = (
        FOR cid IN @topic_ids
          LET base = DOCUMENT(cid)
          FOR sub IN 0..3 INBOUND base._id @@concept_is_a
            RETURN sub._id
      )
      FOR doc IN documents
        FOR edge IN doc_covers_concept
          FILTER edge._from == doc._id
          FILTER edge._to IN concept_family
          FILTER doc.is_current == true
          FILTER edge.authority == @authority_level
          SORT doc.authority_score DESC, doc.effective_date DESC
          LIMIT 3
          RETURN {
            document_id:       doc.document_id,
            title:             doc.title,
            doc_type:          doc.doc_type,
            version:           doc.version,
            pageindex_tree_id: doc.pageindex_tree_id,
            matched_concept:   DOCUMENT(edge._to).label,
            authority:         edge.authority
          }

    post_action: tool_call
    tool_call:
      toolkit: PageIndexToolkit
      method: search_documents_scoped
      credential_mode: service_account            # PageIndex needs no per-user creds
      parameters:
        tree_ids: "{{ graph.rows | map_attr('pageindex_tree_id') | json }}"
        query:    "{{ ctx.original_query }}"
        include_tree_context: false
      result_binding: pageindex_hits
      empty_team_behavior: short_circuit
```

The per-tenant authority file `{ontology_dir}/authority/{tenant_id}.yaml` carries only `covers_topic` and `is_a` edge instances and uses the existing `extends:` merger semantics:

```yaml
name: authority-acme
extends: knowledge
version: "1.0"

edges:
  - { collection: doc_covers_concept, from: documents/sales-commissions-policy, to: concepts/commissions, properties: { authority: "primary", confidence: 1.0, asserted_by: "curator:jesus" } }
  - { collection: concept_is_a,        from: concepts/sales-commissions,        to: concepts/commissions,    properties: {} }
```

> **Note:** The exact YAML key for raw edge data (`edges:` vs `data:`) depends on whether the merger currently supports edge-instance loading. If not (likely — `merger.py:26-130` shows it merges schemas, not data), then loading edges into ArangoDB is an ETL/seed responsibility; the YAML file is a curator-readable manifest that a seed script applies. **This is captured as Open Question §8 (YAML edge ingestion mechanism)** — to be resolved during Module 1.

### New Public Interfaces

```python
# parrot/tools/pageindex_toolkit.py

class SearchScopedInput(BaseModel):
    tree_ids: list[str] = Field(..., description="PageIndex tree IDs to scope the search to")
    query: str = Field(..., description="Free-form natural-language query")
    include_tree_context: bool = Field(default=False, description="If true, include the per-tree tree_context blob in results")
    model_config = ConfigDict(extra="forbid")


class PageIndexToolkit(AbstractToolkit):  # existing class

    @tool_schema(SearchScopedInput)
    async def search_documents_scoped(
        self,
        tree_ids: list[str],
        query: str,
        include_tree_context: bool = False,
    ) -> dict[str, Any]:
        """Search a SUBSET of indexed trees rather than the full collection.

        Iterates over the provided tree_ids and calls the existing
        PageIndexRetriever.search() + retrieve() for each. Returns merged
        scoped_results with per-tree node_list, thinking, and context.
        Silently skips tree_ids not present in self._indices (logs warning).
        Returns {"status": "ok", "scoped_results": [...]} or {"status": "empty"}.
        """
```

```python
# parrot/knowledge/ontology/concept_embedding.py  (new module)

class ConceptEmbeddingPipeline:
    def __init__(
        self,
        vector_store: PgVectorStore,
        embedder: AbstractClient,
        ontology_dir: Path,
        schema: str = "ontology",
        table: str = "concepts",
    ) -> None: ...

    async def sync(
        self,
        tenant_id: str,
        concepts: list[ConceptDef],   # from MergedOntology.entities["Concept"].instances
    ) -> ConceptSyncResult:
        """Idempotent. Computes content hashes, diffs against on-disk cache
        at {ontology_dir}/.concept_hashes/{tenant_id}.json, embeds changed/new
        Concepts, deletes removed ones from the shared 'concepts' namespace
        with tenant_id metadata. Returns counts of added/updated/removed/unchanged.
        """
        ...


@dataclass(frozen=True)
class ConceptSyncResult:
    added: int
    updated: int
    removed: int
    unchanged: int
    duration_ms: int
```

```python
# parrot/stores/postgres.py — extensions to existing class

class PgVectorStore:  # existing
    async def search(
        self,
        query: Any,                                      # existing
        schema: str = ...,                               # existing
        # ... other existing params ...
        metadata_filters: dict[str, Any] | None = None,  # NEW
        **kwargs,
    ) -> list[Any]:
        """When metadata_filters is provided, ANDs each (key, value) into the
        WHERE clause:
          - scalar value → `metadata->>'{key}' = '{value}'`
          - list value   → `metadata->>'{key}' IN (...)`
        Values are bound via parameter substitution to prevent injection."""

    async def add_documents(

…(truncated)…
