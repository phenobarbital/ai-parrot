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
        self,
        # ... existing params ...
        metadata_filters: dict[str, Any] | None = None,  # NEW — used for upsert delete-and-insert scope
        **kwargs,
    ) -> Any: ...
```

```python
# parrot/knowledge/ontology/entity_resolver.py — strategy added inside FEAT-158's EntityResolver

class EntityResolver:  # existing (FEAT-158)
    async def _resolve_hybrid_concept_match(
        self,
        rule: EntityExtractionRule,
        mention: str,
        user_context: dict[str, Any],
        tenant_id: str,
    ) -> list[str]:
        """Returns list of resolved Concept _ids (multi-concept aware).
        Algorithm:
          1. Synonym/fuzzy exact match over ontology.entities['Concept'].instances:
             if confidence > 0.95 → return [hit]
          2. PgVectorStore.search on 'concepts' namespace,
             metadata_filters={'tenant_id': tenant_id}, top_k=10
             if top_1.score > 0.85 AND > 1.3 * top_2.score → return [top_1]
          3. LLM tie-breaker over top-5:
             system prompt asks model to return JSON array of selected concept_ids;
             validated against the candidate pool.
        Multi-concept queries: when the mention parses as a conjunction
        ('A and B', 'A y B', 'A vs B'), all three stages are run per term
        and results are unioned (deduplicated by _id).
        """
```

---

## 3. Module Breakdown

### Module 1: YAML knowledge layer
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/knowledge.ontology.yaml` (new)
- **Responsibility**: Declare `Document` and `Concept` entities, `covers_topic` and `is_a` relations, and the `authoritative_doc_for_topic` traversal pattern. Add a golden test that loads it through the existing `OntologyMerger` and round-trips without loss. Also adds the on-disk convention `{ontology_dir}/authority/{tenant_id}.yaml` for per-tenant edge files; this module documents the convention and adds the loader hook in `TenantOntologyManager.resolve` to also look under `authority/`.
- **Depends on**: (none — pure YAML + a small loader-path addition in `tenant.py`)

### Module 2: ConceptEmbeddingPipeline
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_embedding.py` (new)
- **Responsibility**: Content-hash-based idempotent embedding sync into the shared `concepts` PgVector namespace with `tenant_id` metadata. Reads `MergedOntology.entities["Concept"].instances`, writes hash cache to `{ontology_dir}/.concept_hashes/{tenant_id}.json`, calls `PgVectorStore.add_documents(metadata_filters={"tenant_id": tenant_id})` for upserts and a parallel delete path for removed concepts.
- **Depends on**: Module 4 (PgVectorStore.metadata_filters), existing `MergedOntology`, existing embedding client.

### Module 3: TenantOntologyManager integration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py` (modify)
- **Responsibility**: After `resolve(tenant_id, domain)` returns the merged ontology, invoke `ConceptEmbeddingPipeline.sync(tenant_id, concepts)` asynchronously. Failures log and do not block resolve. Also adds the `authority/` directory to the loader path so per-tenant edge YAMLs are picked up.
- **Depends on**: Modules 1 and 2.

### Module 4: PgVectorStore.metadata_filters
- **Path**: `packages/ai-parrot/src/parrot/stores/postgres.py` (modify)
- **Responsibility**: Add `metadata_filters: dict[str, Any] | None = None` to `search()` and `add_documents()`. ANDs into WHERE clause; scalar → equality, list → `IN (...)`. Parameter-bound to prevent injection. Backwards-compatible: absent or `None` leaves today's behavior untouched.
- **Depends on**: (none — pure extension to existing class)

### Module 5: hybrid_concept_match resolver strategy
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` (modify — extends FEAT-158)
- **Responsibility**: Implement the strategy that FEAT-158 declared with `NotImplementedError`. Synonym/fuzzy → vector → LLM tie-breaker. Multi-concept parsing. Returns `list[str]` (FEAT-158's strategy returns `str`; this strategy relaxes the value type for multi-concept rules). Result cached by `(query_hash, ontology_version, tenant_id)` using the existing cache helper from FEAT-158's resolver module if any, otherwise an LRU cache.
- **Depends on**: Modules 2 and 4 (vector store + populated concepts namespace).

### Module 6: PageIndexToolkit.search_documents_scoped
- **Path**: `packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py` (modify)
- **Responsibility**: New tool method + `SearchScopedInput` pydantic model. Iterates over `_indices.get(tree_id)` for each tree_id; silently skips missing trees (logs warning); calls the existing `retriever.search()` + `retriever.retrieve()` per tree. Returns `{"status": "ok"|"empty", "scoped_results": [...]}`. Each result carries `tree_id`, `doc_name`, `node_list`, `thinking`, `context`.
- **Depends on**: (none — pure addition to existing class)

### Module 7: ontology_process degradation chain
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` (modify — extends FEAT-158's refactor)
- **Responsibility**: After FEAT-158's refactored body lands, wrap the traversal+tool_call block in the 4-level chain. Tag `envelope.context.source` per level: `graph:primary`, `graph:secondary`, `vector:filtered`, `vector:plain`. The secondary retry executes the same traversal with `@authority_level="secondary"` bound; filtered vector calls `PgVectorStore.search(..., metadata_filters={"doc_type": ["policy","manual"]})`; plain vector is the existing `_do_vector_search` path. Ambiguity/denial/auth_required envelope states from FEAT-158 bypass the chain (they short-circuit the flow before traversal).
- **Depends on**: Modules 4, 6, and FEAT-158 Module 5.

### Module 8: IntentRouterMixin branch logic
- **Path**: `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` (modify — minor)
- **Responsibility**: After FEAT-158's fix to `_run_graph_pageindex`, refine the branch logic so unscoped `PageIndexRetriever.retrieve` is only called when `envelope.state == "ok"` AND `envelope.context.graph_context` is empty AND `envelope.context.vector_context` is empty (i.e., the degradation chain itself returned nothing — only possible when no concept is modeled AND vector retrieval is disabled or empty). Otherwise pass through `envelope.context` formatted with provenance.
- **Depends on**: Module 7.

### Module 9: End-to-end tests + golden fixtures
- **Path**: `packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py` (new), `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/` (new)
- **Responsibility**: Driving use case validation. Fixtures:
  - 3 Documents (sales-commissions-policy, commissions-faq, commissions-memo) with `pageindex_tree_id`s pre-populated.
  - 1 Concept (commissions) + 1 sub-Concept (sales-commissions) linked via `is_a`.
  - `covers_topic` edges: policy=primary, faq=mentions, memo=mentions.
  - Mocked PageIndex `_indices` so `search_documents_scoped` returns deterministic snippets.
  - Mocked vector store with `metadata_filters` honored.
- Tests cover: known-concept → primary doc routed; sub-concept → parent's primary doc via `is_a`; multi-concept union; unknown concept → vector fallback labeled; concept synonyms updated → re-embedding triggered; equal `authority_score` → deterministic ordering.
- **Depends on**: All prior modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_knowledge_yaml_loads_and_merges` | Module 1 | YAML round-trips through `OntologyMerger`; new entities/relations/pattern appear in `MergedOntology` with correct shapes. |
| `test_authority_per_tenant_yaml_loaded` | Module 1 + 3 | Per-tenant `authority/<tenant>.yaml` is picked up by `TenantOntologyManager.resolve` and surfaces in the merged ontology. |
| `test_concept_embedding_pipeline_first_run` | Module 2 | 5 Concepts, no hash cache → all 5 embedded, hash cache written; `added=5, updated=0, removed=0`. |
| `test_concept_embedding_pipeline_no_change` | Module 2 | Re-run with identical concepts → `added=0, updated=0, removed=0, unchanged=5`; no embedding calls made. |
| `test_concept_embedding_pipeline_synonym_changed` | Module 2 | Add a synonym to one concept → only that concept re-embedded (`updated=1`); hash cache reflects new hash. |
| `test_concept_embedding_pipeline_concept_removed` | Module 2 | Remove a concept from YAML → corresponding rows deleted via `metadata_filters={"tenant_id": …, "concept_id": …}`; `removed=1`. |
| `test_concept_embedding_pipeline_tenant_isolation` | Module 2 | Two tenants with overlapping concept_ids produce non-overlapping rows; each tenant's `search` only sees its own. |
| `test_tenant_manager_invokes_pipeline` | Module 3 | `TenantOntologyManager.resolve(tenant_id)` calls `ConceptEmbeddingPipeline.sync` exactly once with the tenant's concepts. |
| `test_tenant_manager_pipeline_failure_is_logged_not_raised` | Module 3 | Pipeline raises → resolve still returns; failure is logged at WARNING. |
| `test_pgvector_metadata_filters_scalar_eq` | Module 4 | `metadata_filters={"tenant_id": "acme"}` adds `metadata->>'tenant_id' = 'acme'` to WHERE; bound, not interpolated. |
| `test_pgvector_metadata_filters_list_in` | Module 4 | `metadata_filters={"doc_type": ["policy", "manual"]}` adds `metadata->>'doc_type' IN ('policy', 'manual')` to WHERE. |
| `test_pgvector_metadata_filters_injection_safe` | Module 4 | `metadata_filters={"tenant_id": "a' OR 1=1 --"}` is parameter-bound; query result is empty (no row matches the literal string). |
| `test_pgvector_metadata_filters_absent` | Module 4 | `metadata_filters=None` or omitted → query identical to today's. |
| `test_pgvector_metadata_filters_add_documents_upsert` | Module 4 | `add_documents(metadata_filters={"tenant_id": "acme"})` deletes existing rows matching filter before insert. |
| `test_hybrid_resolver_synonym_dominant` | Module 5 | Mention `"commissions"` matches `Concept(synonyms=["commissions", "comp"])` exactly → returns `[that_id]` without any vector or LLM call. |
| `test_hybrid_resolver_vector_clearly_dominant` | Module 5 | Synonym path misses; vector top-1 score=0.91, top-2=0.62 → returns `[top_1]` without LLM call. |
| `test_hybrid_resolver_llm_tiebreaker` | Module 5 | Synonym misses; vector top-1=0.82, top-2=0.78 → LLM tie-breaker invoked with top-5; returns LLM's selection. |
| `test_hybrid_resolver_tenant_filter` | Module 5 | Two tenants own different concepts; resolver called with `tenant_id="acme"` does not return concepts from `tenant_id="globex"`. |
| `test_hybrid_resolver_multi_concept_conjunction_en` | Module 5 | `"how do commissions and bonuses differ?"` → returns `[commissions_id, bonuses_id]` (union, deduplicated). |
| `test_hybrid_resolver_multi_concept_conjunction_es` | Module 5 | `"comisiones y bonos"` → returns `[commissions_id, bonuses_id]`. |
| `test_hybrid_resolver_cache_hit` | Module 5 | Same `(query_hash, ontology_version, tenant_id)` → second call does not invoke vector or LLM. |
| `test_hybrid_resolver_cache_invalidates_on_ontology_version_bump` | Module 5 | Bump ontology version → cache miss → fresh resolution. |
| `test_pageindex_scoped_search_basic` | Module 6 | `_indices` has 3 trees; call with two of the three → only those two get `retriever.search()`+`retrieve()` invoked. |
| `test_pageindex_scoped_search_missing_tree_silent_skip` | Module 6 | `tree_ids=["a","b","ghost"]` where `ghost` not in `_indices` → result contains 2 entries, warning logged for `ghost`. |
| `test_pageindex_scoped_search_empty_input` | Module 6 | `tree_ids=[]` → returns `{"status": "empty", "scoped_results": []}` without invoking PageIndex. |
| `test_pageindex_scoped_search_includes_per_tree_context` | Module 6 | `include_tree_context=True` → each `scoped_results` entry contains the per-tree `tree_context` blob. |
| `test_degradation_primary_hit` | Module 7 | Concept matched, primary edge exists → `state="ok"`, `context.source="graph:primary"`, `context.graph_context` populated, no secondary retry, no vector fallback. |
| `test_degradation_relax_to_secondary` | Module 7 | Concept matched, no primary, one secondary → second traversal executes with `authority="secondary"`, returns docs, `context.source="graph:secondary"`. |
| `test_degradation_filtered_vector` | Module 7 | Concept extraction returns nothing → primary skipped → filtered vector called with `metadata_filters={"doc_type": ["policy","manual"]}`; `context.source="vector:filtered"`. |
| `test_degradation_plain_vector` | Module 7 | Filtered vector returns empty → plain vector called; `context.source="vector:plain"`. |
| `test_degradation_ambiguity_bypasses_chain` | Module 7 | Resolver raises `EntityAmbiguityError` → envelope `state="ambiguous"`; degradation chain is NOT entered. |
| `test_degradation_auth_required_bypasses_chain` | Module 7 | Toolkit raises `AuthorizationRequired` during tool_call → envelope `state="auth_required"`; chain NOT entered. (For PageIndex this shouldn't happen, but the test guards the invariant.) |
| `test_intent_router_branches_on_state_ok` | Module 8 | `envelope.state="ok"` with `graph_context` populated → formatted output with provenance; unscoped PageIndex NOT called. |
| `test_intent_router_fallback_when_envelope_empty` | Module 8 | `envelope.state="ok"` with empty graph + empty vector → unscoped `PageIndexRetriever.retrieve(prompt)` is the last resort. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_commissions_routes_to_policy` | Acme tenant, query *"how do commissions work?"* → returns context grounded in the sales-commissions-policy tree (primary), NOT the FAQ or memo. Assert `envelope.context.source == "graph:primary"`. |
| `test_e2e_sub_concept_routes_to_parent_primary` | Query *"how do sales commissions work?"* → resolver picks `sales-commissions`; traversal walks `is_a` to `commissions`; returns the policy doc (linked at the parent). `matched_concept` in graph_context is "sales-commissions" (the leaf). |
| `test_e2e_multi_concept_union` | Query *"how do commissions and bonuses differ?"* → both concepts resolved; traversal returns docs for both (union, deduplicated); LLM receives both contexts labeled. Assert at least 2 distinct `pageindex_tree_id`s in result. |
| `test_e2e_unknown_concept_vector_fallback` | Query *"what's the holiday roster?"* with no `holiday` concept modeled → degradation chain falls through to vector; `envelope.context.source` is `vector:filtered` (if matching doc_type) or `vector:plain`. |
| `test_e2e_no_primary_falls_to_secondary` | Concept matched but only secondary edges exist → secondary traversal succeeds; `envelope.context.source == "graph:secondary"`. |
| `test_e2e_concept_synonyms_re-embedding` | Add synonym to a Concept in YAML, re-resolve tenant → only that concept's row in `concepts` namespace is rewritten; new mention of the synonym now resolves correctly. |
| `test_e2e_two_primaries_deterministic_order` | Two policy docs both `primary` with identical `authority_score` → ordering is deterministic across two consecutive runs (verified by `effective_date DESC` then `created_at DESC` tie-break). |
| `test_e2e_pageindex_tree_id_missing_silent` | One of the resolved documents references a `pageindex_tree_id` that is NOT in `_indices` → `search_documents_scoped` logs a warning and returns results for the remaining trees; envelope is `state="ok"` not `state="tool_failed"`. |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/knowledge/fixtures/concept_authority/

@pytest.fixture
def acme_ontology(tmp_path) -> MergedOntology:
    """Loads knowledge.ontology.yaml + authority/acme.yaml for the test corpus:
       - Documents: sales-commissions-policy (v3.2, primary for commissions),
                    commissions-faq (mentions), commissions-memo (mentions),
                    bonus-policy (primary for bonuses).
       - Concepts: commissions (parent), sales-commissions (is_a commissions),
                   bonuses, pto.
       - covers_topic edges seeded.
    """

@pytest.fixture
def pageindex_toolkit_with_indices():
    """PageIndexToolkit with three trees pre-loaded into _indices,
    each tree's retriever mocked to return deterministic snippets
    keyed by query."""

@pytest.fixture
def pgvector_with_concepts(acme_ontology):
    """In-memory PgVectorStore double populated by ConceptEmbeddingPipeline.sync(),
    honors metadata_filters."""

@pytest.fixture
def envelope_capture():
    """Spy that records the ContextEnvelope returned by ontology_process
    for assertion in tests."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `knowledge.ontology.yaml` loads through `OntologyMerger`; the merged ontology exposes `Document`, `Concept`, `covers_topic`, `is_a`, and the `authoritative_doc_for_topic` traversal pattern with no validation errors.
- [ ] Per-tenant `authority/<tenant>.yaml` is picked up by `TenantOntologyManager.resolve()` and surfaces in the resolved tenant context.
- [ ] `ConceptEmbeddingPipeline.sync()` is idempotent: re-running on unchanged YAML produces `added=0, updated=0, removed=0`.
- [ ] Adding a synonym to one Concept in YAML and re-syncing re-embeds **only** that concept; the on-disk hash cache reflects the new hash.
- [ ] Removing a Concept from YAML and re-syncing deletes the corresponding rows from the shared `concepts` PgVector namespace, scoped by `metadata_filters={"tenant_id": tenant_id}`.
- [ ] `PgVectorStore.search()` accepts `metadata_filters` as a generic dict; scalar values → `metadata->>'k' = 'v'`, list values → `IN (...)`. SQL-injection adversarial test passes (literal string match returns 0 rows).
- [ ] `PgVectorStore.add_documents()` accepts `metadata_filters` to scope upsert delete-and-insert.
- [ ] `EntityResolver`'s `hybrid_concept_match` strategy replaces FEAT-158's `NotImplementedError`; the cascade synonym → vector → LLM is exercised in the test matrix; tenant_id filtering is enforced at the vector step.
- [ ] `hybrid_concept_match` returns `list[str]` for multi-concept queries (English conjunctions "and", "vs", Spanish "y", "vs", "frente a"); single-concept queries return a 1-element list.
- [ ] `PageIndexToolkit.search_documents_scoped(tree_ids, query, include_tree_context)` exists as a tool with a `SearchScopedInput` pydantic schema and is discoverable via `ToolManager.get_tool("PageIndexToolkit.search_documents_scoped")`.
- [ ] `search_documents_scoped` calls the existing `PageIndexRetriever.search` + `retrieve` for each provided tree_id; missing tree_ids are silently skipped with a WARNING log; empty `tree_ids` returns `{"status": "empty"}` without invoking PageIndex.
- [ ] `OntologyRAGMixin.ontology_process` produces `ContextEnvelope.context.source` ∈ `{"graph:primary", "graph:secondary", "vector:filtered", "vector:plain"}` for the four levels of the degradation chain.
- [ ] The four levels are entered in order; each is skipped only when the previous level returned a non-empty result.
- [ ] `state ∈ {"ambiguous", "denied", "auth_required", "render_error"}` envelopes from FEAT-158 bypass the degradation chain (no spurious vector fallback when authorization is the issue).
- [ ] End-to-end test `test_e2e_commissions_routes_to_policy` passes: query *"how do commissions work?"* returns context grounded in the Sales Commissions Policy primary document, regardless of the existence of higher-similarity memos.
- [ ] End-to-end test `test_e2e_sub_concept_routes_to_parent_primary` passes: a query for a sub-concept walks `is_a` to find the parent's primary document.
- [ ] End-to-end test `test_e2e_multi_concept_union` passes: two distinct concepts → union of primaries returned.
- [ ] End-to-end test `test_e2e_two_primaries_deterministic_order` passes: equal-`authority_score` ordering is identical across two consecutive runs.
- [ ] `IntentRouterMixin._run_graph_pageindex` calls unscoped `PageIndexRetriever.retrieve(prompt)` only when the envelope returns `state="ok"` with both `graph_context` and `vector_context` empty (i.e., the degradation chain itself surfaced nothing).
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/test_concept_embedding.py tests/knowledge/test_hybrid_resolver.py tests/tools/test_pageindex_scoped.py tests/stores/test_pgvector_metadata_filters.py tests/knowledge/test_degradation_chain.py -v`.
- [ ] All integration tests pass: `pytest packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py -v`.
- [ ] No regression in PageIndex tests or in FEAT-158's `test_entity_extraction_e2e.py`.
- [ ] FEAT-158's `OntologyIntentResolver` and `_pre_execute` credential flow remain untouched.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

> All entries verified on 2026-05-11 against branch `dev`.

### Verified Imports

```python
# PageIndex
from parrot.pageindex.retriever import PageIndexRetriever           # retriever.py:11
from parrot.tools.pageindex_toolkit import PageIndexToolkit         # pageindex_toolkit.py:39
from parrot.tools.decorators import tool_schema                     # decorators.py:37

# Ontology (FEAT-158 provides EntityResolver, ToolCallDispatcher, ContextEnvelope;
# this feature consumes them — do NOT redefine):
from parrot.knowledge.ontology.schema import (
    TraversalPattern,         # schema.py:131
    ResolvedIntent,           # schema.py:279
    EntityDef,                # schema.py:39
    RelationDef,              # schema.py:106
    MergedOntology,           # schema.py:185
    EnrichedContext,          # schema.py:303
    # The following are added by FEAT-158 and must be present before this feature merges:
    # EntityExtractionRule, ToolCallSpec, AuthorizationSpec, ContextEnvelope
)
from parrot.knowledge.ontology.mixin import OntologyRAGMixin        # mixin.py:27
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # tenant.py:18
from parrot.knowledge.ontology.merger import OntologyMerger         # merger.py:26
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # graph_store.py:33
from parrot.knowledge.ontology.cache import OntologyCache           # cache.py:43

# Bots / Router
from parrot.bots.mixins.intent_router import IntentRouterMixin      # intent_router.py:107

# Vector store
from parrot.stores.postgres import PgVectorStore                    # postgres.py:58

# Tools framework
from parrot.tools.manager import ToolManager                        # manager.py:203
from parrot.tools.toolkit import AbstractToolkit                    # toolkit.py:168
```

### Existing Class Signatures

```python
# parrot/pageindex/retriever.py
class PageIndexRetriever:                                          # line 11
    async def search(self, query: str) -> "TreeSearchResult":      # line 38
        ...
    async def retrieve(
        self,
        query: str,
        pdf_pages: Optional[list[tuple[str, int]]] = None,
    ) -> str:                                                       # line 81
        ...

# parrot/tools/pageindex_toolkit.py
class PageIndexToolkit(AbstractToolkit):                           # line 39
    _indices: dict[str, dict[str, Any]]                            # line 63
    # Structure: {index_id: {"tree": <tree>, "retriever": PageIndexRetriever}}

    @tool_schema(IndexDocumentsInput)
    async def index_documents(
        self,
        documents: list[str],
        document_names: Optional[list[str]] = None,
    ) -> dict[str, Any]:                                           # line 72
        ...

    @tool_schema(SearchDocumentsInput)
    async def search_documents(
        self,
        index_id: str,
        query: str,
        include_tree_context: bool = False,
    ) -> dict[str, Any]:                                           # line 114
        ...

# parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):    # line 37
    """Attaches a pydantic schema and description to a tool method."""

# parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                           # line 107
    async def _run_graph_pageindex(
        self,
        prompt: str,
        candidates: list[RouterCandidate],
    ) -> Optional[str]:                                            # line 615
        # AFTER FEAT-158 lands: forwards user_context + tenant_id to ontology_process,
        # and the silent try/except Exception: pass is narrowed to a logged catch.
        # This feature ONLY refines branch logic on ContextEnvelope.state.

# parrot/knowledge/ontology/mixin.py
class OntologyRAGMixin:                                            # line 27
    async def ontology_process(
        self,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
        domain: str | None = None,
    ) -> "ContextEnvelope":                                        # line 65
        # AFTER FEAT-158 lands: composes EntityResolver + AuthorizationChecker + ToolCallDispatcher.
        # Return type is ContextEnvelope (not EnrichedContext).
        # This feature wraps the traversal+tool_call block in the 4-level degradation chain.

    @staticmethod
    def _build_tool_hint(graph_result: list[dict[str, Any]]) -> str:    # mixin.py:235

# parrot/knowledge/ontology/tenant.py
class TenantOntologyManager:                                       # line 18
    async def resolve(
        self,
        tenant_id: str,
        domain: str | None = None,
    ) -> "TenantContext":                                          # line 74
        # This feature hooks ConceptEmbeddingPipeline.sync() into the resolve flow.

# parrot/knowledge/ontology/merger.py
class OntologyMerger:                                              # line 26
    def merge(self, yaml_paths: list[Path]) -> "MergedOntology":   # line 51
        # Layered merge:
        #   - entities with extend=True: properties concatenated, vectorize unioned
        #   - relations: new added; same name → endpoints immutable, discovery rules concatenated
        #   - traversal patterns: trigger_intents deduped/concatenated, query_template/post_action overridden
        # Verified: accepts new entity definitions and traversal patterns without modification.

# parrot/knowledge/ontology/cache.py
class OntologyCache:
    @staticmethod
    def build_key(
        tenant_id: str,
        user_id: str,
        pattern: str,
        # AFTER FEAT-158 lands:
        resolved_entities: dict[str, str] | None = None,
    ) -> str:                                                       # line 43

# parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:                                          # line 33
    async def execute_traversal(
        self,
        ctx: "TenantContext",
        aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:                                     # line 185

# parrot/stores/postgres.py
class PgVectorStore:                                               # line 58
    def __init__(self, schema: str = 'public', ...):               # line 66
    async def add_documents(self, schema=..., table=..., ...):     # line 592
    async def search(self, query, schema=..., ...):                # line 745
    # NOTE: today, tenant separation is by `schema=` parameter.
    # This feature ADDS a generic `metadata_filters: dict | None = None`
    # parameter to .search() and .add_documents() for row-level filtering.

# parrot/knowledge/ontology/schema.py — FEAT-158 additions consumed (do NOT redefine)
class EntityExtractionRule(BaseModel):                             # added by FEAT-158
    type: str
    resolver: Literal[
        "exact_id_match", "fuzzy_name_match", "ai_assisted", "hybrid_concept_match",
    ]
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
    ambiguity_strategy: Literal[
        "ask_user", "pick_first", "use_context", "fail", "rerank_by_authority",
    ] = "ask_user"
    required: bool = True

class ToolCallSpec(BaseModel):                                     # added by FEAT-158
    toolkit: str
    method: str
    credential_mode: Literal["requesting_user", "service_account", "agent_owner"] = "requesting_user"
    parameters: dict[str, Any]
    result_binding: str
    empty_team_behavior: Literal["short_circuit", "call_anyway", "fail"] = "short_circuit"

class ContextEnvelope(BaseModel):                                  # added by FEAT-158
    state: Literal[
        "ok", "ambiguous", "entity_not_found", "denied",
        "auth_required", "render_error", "tool_failed",
    ]
    context: EnrichedContext | None = None
    clarification: dict[str, Any] | None = None
    denial_reason: str | None = None
    auth_prompt: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    error: str | None = None
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| YAML `knowledge.ontology.yaml` | `OntologyMerger.merge` | layered YAML load | `merger.py:51` |
| `ConceptEmbeddingPipeline.sync` | `PgVectorStore.add_documents` | `metadata_filters={"tenant_id": tenant_id}` | `postgres.py:592` (extended in Module 4) |
| `TenantOntologyManager.resolve` (extended) | `ConceptEmbeddingPipeline.sync` | post-merge hook | `tenant.py:74` |
| `EntityResolver._resolve_hybrid_concept_match` | `PgVectorStore.search` | `metadata_filters={"tenant_id": tenant_id}` | `postgres.py:745` (extended in Module 4) |
| `EntityResolver._resolve_hybrid_concept_match` | `MergedOntology.entities["Concept"].instances` | in-memory synonym scan | `schema.py:185` |
| YAML traversal `authoritative_doc_for_topic` | `EntityResolver.extract_and_resolve` | `entity_extraction` block | FEAT-158 Module 2 |
| YAML traversal `authoritative_doc_for_topic` | `ToolCallDispatcher.dispatch` | `post_action: tool_call` + `tool_call:` block | FEAT-158 Module 4 |
| `ToolCallDispatcher.dispatch` | `PageIndexToolkit.search_documents_scoped` | `ToolManager.get_tool("PageIndexToolkit.search_documents_scoped")` | `manager.py:822`; Module 6 |
| `PageIndexToolkit.search_documents_scoped` | `PageIndexRetriever.search` + `.retrieve` | per-tree iteration over `_indices` | `retriever.py:38, 81`; `pageindex_toolkit.py:63` |
| `OntologyRAGMixin.ontology_process` (degradation chain) | `PgVectorStore.search` filtered | `metadata_filters={"doc_type": ["policy","manual"]}` | `postgres.py:745` (extended in Module 4) |
| `OntologyRAGMixin.ontology_process` (degradation chain) | existing `_do_vector_search` | plain vector RAG fallback | `mixin.py` |
| `IntentRouterMixin._run_graph_pageindex` | `OntologyRAGMixin.ontology_process` | already forwards `user_context` + `tenant_id` (FEAT-158); this feature refines branch on `envelope.state` | `intent_router.py:615` |

### Does NOT Exist (Anti-Hallucination)

These look plausible but are NOT in the codebase. Implementation agents MUST NOT reference them:

- ~~`parrot.knowledge.ontology.entity_resolver.EntityResolver`~~ on `dev` today — added by FEAT-158. This feature MUST be merged on top of FEAT-158 (which is FEAT-158 / `sdd/specs/ontology-entity-extraction.spec.md`).
- ~~`parrot.knowledge.ontology.tool_dispatcher.ToolCallDispatcher`~~ on `dev` today — added by FEAT-158.
- ~~`EntityExtractionRule`, `ToolCallSpec`, `ContextEnvelope` on `dev` today~~ — added by FEAT-158 in `schema.py`.
- ~~`ResolvedIntent.resolved_entities`~~ on `dev` today — added by FEAT-158.
- ~~`PgVectorStore.search()` accepting a `metadata_filters` kwarg today~~ — does NOT exist; added by Module 4 of this feature.
- ~~`PageIndexToolkit.search_documents_scoped`~~ on `dev` today — does NOT exist; added by Module 6 of this feature.
- ~~`PageIndexToolkit.search_documents`~~ accepting a `tree_ids` list parameter — does NOT exist; current `search_documents(index_id, query, include_tree_context)` takes a single `index_id`. Do NOT extend it in place; add `search_documents_scoped` as a new method.
- ~~`Document.pageindex_tree_id` as an ontology entity property today~~ — defined for the first time by this feature's YAML.
- ~~An existing concept-embedding pipeline on the `TenantOntologyManager` path~~ — does NOT exist; first introduced by Module 2.
- ~~An existing `concepts` PgVector namespace~~ — does NOT exist; created on first run of `ConceptEmbeddingPipeline.sync()` per tenant (shared schema, rows scoped by `metadata.tenant_id`).
- ~~A traversal pattern that accepts a list-valued bind var `@topic_ids` already wired through `OntologyGraphStore.execute_traversal`~~ — the API at `graph_store.py:185` accepts arbitrary `bind_vars`, so this works, but no existing pattern uses a list-valued bind. This feature's `authoritative_doc_for_topic` is the first.
- ~~`EnrichedContext.source` accepting the value `"graph:primary"` today~~ — the field exists (`schema.py:318`) as a free-form string, but the four labels `"graph:primary" | "graph:secondary" | "vector:filtered" | "vector:plain"` are introduced by Module 7. Document the convention in the mixin module docstring.
- ~~An out-of-the-box loader for `{ontology_dir}/authority/<tenant>.yaml`~~ — `TenantOntologyManager.resolve()` does NOT scan this directory today; Module 1+3 add the path.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first.** Every public method on the new modules is `async`. The concept-embedding pipeline runs inside `TenantOntologyManager.resolve` — do NOT block.
- **Pydantic v2** with `ConfigDict(extra="forbid")` for `SearchScopedInput` and any new models.
- **Logger over print.** Each new module: `self.logger = logging.getLogger(__name__)`.
- **Idempotent embedding pipeline.** sha256 of `label + sorted(synonyms) + description`. Write hash cache atomically (tmpfile + rename) to avoid corruption on crash.
- **Parameter-bound SQL.** `PgVectorStore.metadata_filters` MUST use psycopg parameter substitution, never f-string interpolation. The `test_pgvector_metadata_filters_injection_safe` test enforces this.
- **AQL bind vars for list values.** `@topic_ids` is bound as a list; `FOR cid IN @topic_ids` is standard AQL. `@authority_level` is bound per-degradation-step (primary then secondary).
- **Jinja2 filters reuse.** The traversal `tool_call.parameters.tree_ids` template uses `map_attr` and `json` filters — both registered by FEAT-158's `ToolCallDispatcher`. Do NOT reimplement.
- **`scoped_results` envelope shape.** Each entry: `{"tree_id": str, "doc_name": str | None, "node_list": list, "thinking": str, "context": str}`. This shape is consumed downstream by the LLM-formatting layer of the agent — keep it stable.
- **Multi-concept conjunction detection.** Use a small regex set (English: `\bvs?\.?\b`, `\band\b`; Spanish: `\bvs?\.?\b`, `\b[ye]\b`, `\bfrente a\b`). Do NOT use the LLM for the *splitting* step — only for tie-breaking within each term. Keep this deterministic.
- **Concept hash file location.** `{ontology_dir}/.concept_hashes/{tenant_id}.json` — keep it under `ontology_dir`, not in a random app cache, so it travels with the deployment.
- **Per-tenant authority YAML naming.** `{ontology_dir}/authority/{tenant_id}.yaml`. This is the new convention introduced by Module 1; document it in the ontology README.

### Known Risks / Gotchas

- **Hard dependency on FEAT-158.** This feature cannot land on `dev` until FEAT-158 has merged (or the two are merged together). Specifically, the YAML traversal pattern uses `entity_extraction` and `tool_call`, both of which require FEAT-158's schema additions. Surface this explicitly in the PR description and Open Questions §8.
- **Concept ontology bloat.** Without governance, every domain noun becomes a Concept. Mitigation: FEAT-topic-authority-operational owns lifecycle; for v1, document the curation discipline in the ontology README (one Concept per *retrieval intent*, not per *noun*).
- **Authority drift.** Documents change but edges don't follow. Out of scope for this feature; FEAT-topic-authority-operational owns "stale edge" alerts.
- **`pageindex_tree_id` out of sync with `_indices`.** Document deleted from PageIndex but graph still references it. Mitigated by `search_documents_scoped` silently skipping missing tree_ids and logging WARN — the agent still returns useful results from the remaining trees.
- **Multi-concept queries explode the AQL fan-out.** Cap concept list to 5 in `hybrid_concept_match`; anything beyond is dropped with a debug log. Most real queries top out at 2.
- **Vector-store metadata filtering performance.** Adding `metadata->>'tenant_id' = ?` is a non-trivial WHERE clause on a vector search. Mitigate by creating a partial GIN index on `(metadata->>'tenant_id')` when the `concepts` namespace is first created — document in the module docstring.
- **Concept embedding pipeline running on every resolve.** Mitigated by the hash cache; fast path is just a JSON read + dict diff. But still: if `resolve()` is in the hot path of every request, the file read amortizes. Consider an in-process LRU on top of the file cache if profiling shows it's a hotspot.
- **PageIndex's `search()` is LLM-backed.** Running it across N tree_ids in `search_documents_scoped` costs N LLM calls. Cap `LIMIT 3` in the traversal AQL is the primary throttle. For multi-concept queries with N=5 concepts × 3 docs = 15 trees, this is a real cost — add a hard cap of `max_trees=10` in `search_documents_scoped` (parameter on `SearchScopedInput`; default not exposed to YAML).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` (already pinned) | `SearchScopedInput`, `ConceptSyncResult` schemas |
| `PyYAML` | `>=6` (already pinned) | `knowledge.ontology.yaml` and `authority/<tenant>.yaml` loading via existing `OntologyParser` |
| `hashlib` (stdlib) | — | sha256 for concept content hashing |
| `psycopg` (already used by `PgVectorStore`) | unchanged | Parameter-bound WHERE clause for `metadata_filters` |
| `python-arango` (already used by `OntologyGraphStore`) | unchanged | AQL traversal with list-valued bind vars (already supported) |

No new external dependencies.

---

## Worktree Strategy

**Default isolation unit:** `per-spec` (single worktree, sequential tasks).

**Rationale:** Module 4 (`PgVectorStore.metadata_filters`) is a prerequisite for both Module 2 (embedding pipeline) and Module 5 (hybrid resolver vector path) and Module 7 (filtered vector fallback). Module 1 (YAML) is a prerequisite for Module 9 (e2e tests). Although Module 6 (`search_documents_scoped`) is technically independent, the feature's value emerges only when all modules compose, and spreading them across worktrees would require coordinated rebases on shared YAML fixtures. One worktree off `dev`, with tasks ordered, is the right granularity. The bigger parallelism risk is **with FEAT-158**, not within this feature.

**Cross-feature dependencies (must merge first or coordinate):**
- **FEAT-158 (`ontology-entity-extraction`)** — hard prerequisite. Must merge first OR this feature rebases onto its branch. Specifically required: `EntityResolver`, `ToolCallDispatcher`, `EntityExtractionRule`, `ToolCallSpec`, `ContextEnvelope`, the `ontology_process` refactor, and the `_run_graph_pageindex` fix.
- **FEAT-topic-authority-operational** (downstream) — consumes this feature's `covers_topic` edge model. Does NOT block this spec.
- **FEAT-156 (`agentsflow-refactor-spec3`)** — operates on `parrot.core.node.AgentNode`, no overlap.

**Worktree creation (after task decomposition, after FEAT-158 merges to `dev`):**
```bash
git checkout dev && git pull --ff-only origin dev
git worktree add -b feat-159-concept-document-authority \
  .claude/worktrees/feat-159-concept-document-authority HEAD
```

If FEAT-158 has not yet merged when this feature starts, branch from FEAT-158's branch instead:
```bash
git checkout feat-158-ontology-entity-extraction && git pull
git worktree add -b feat-159-concept-document-authority \
  .claude/worktrees/feat-159-concept-document-authority HEAD
```

---

## 8. Open Questions

> Questions resolved during brainstorm or §2/§4 research are marked `[x]` and carried forward verbatim. Items remaining unresolved are `[ ]`.

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] `Section` as a first-class entity — *Resolved in brainstorm*: No for v1. Revisit if a real use case requires section-level authority.
- [x] Concept hierarchy depth — *Resolved in brainstorm*: `0..3 INBOUND concept_is_a` as default; tunable per tenant via the AQL `LIMIT` (parameterize in a future iteration if needed).
- [x] Concept synonyms across languages — *Resolved in brainstorm*: Single normalized `synonyms` list. Re-evaluate when multilingual tenants surface concrete failure cases.
- [x] Authority tie-break beyond `authority_score` — *Resolved in brainstorm*: `effective_date DESC` secondary, `created_at DESC` tertiary. Deterministic across runs (acceptance test `test_e2e_two_primaries_deterministic_order`).
- [x] Multi-document response composition — *Resolved in brainstorm*: Pass all 2–3 primaries to the LLM with `{doc_type, version, authority}` labels. Implemented by `scoped_results` envelope shape carrying these fields.
- [x] Multi-concept queries at v1 — *Resolved in brainstorm*: Resolve concept list; return UNION of authoritative documents. Intersection optimization deferred.
- [x] Edge curation mechanism for v1 — *Resolved in brainstorm*: YAML-only. No bootstrap script and no LLM auto-proposer at v1; that scope belongs to FEAT-topic-authority-operational.
- [x] PageIndex tree linkage — *Resolved in brainstorm*: ETL writes `pageindex_tree_id` back into the `Document` entity on (re-)ingest. Version-scoped trees; edges target `document_id` (version-agnostic).
- [x] Tenant isolation for concept embeddings — *Resolved in brainstorm*: Shared PgVector namespace, filter by `tenant_id` metadata at query time.
- [x] `PgVectorStore` extension shape for tenant filtering — *Resolved during §3 spec discussion*: generic `metadata_filters: dict[str, Any] | None = None` parameter on `search()` and `add_documents()`. ANDs into WHERE; scalar→equality, list→IN. Reusable for any future per-row filter.
- [x] Per-tenant authority YAML directory location — *Resolved during §3 spec discussion*: `{ontology_dir}/authority/{tenant_id}.yaml`. New sibling directory next to existing `clients/` and `domains/`. Only `covers_topic` and `is_a` edges live there; `Concept` definitions stay in tenant ontology files.
- [x] Ordering with FEAT-ontology-entity-extraction — *Resolved during §2/§6 research*: hard prerequisite. This feature is FEAT-159; FEAT-158 must merge first OR this feature rebases onto FEAT-158's branch. Documented under "Worktree Strategy" and "Known Risks / Gotchas".

Genuinely unresolved (do not block spec, resolve during implementation):

- [ ] **YAML edge ingestion mechanism** — *Owner: Module 1 implementer*: the merger today (`merger.py:26-130`) merges schemas (entity/relation *definitions*) but does not appear to load edge *instances*. Two paths: (a) extend the merger to load a top-level `edges:` array and emit them as ArangoDB inserts, OR (b) keep the YAML as a curator manifest and add a seed script (`scripts/seed_authority_edges.py`) that reads it and writes into ArangoDB directly. Recommend (b) for v1 to keep the merger focused; promote to (a) if a real need emerges.
- [ ] **Concept-embedding pipeline placement on first request vs. on resolve** — *Owner: Module 3 implementer*: `TenantOntologyManager.resolve` may be called on every request. The pipeline is idempotent and fast on the cached path, but on first-resolve-per-process it embeds N concepts which may be 100s of ms. Decide whether to (a) embed synchronously inside resolve (simplest, blocks first request), (b) embed asynchronously and return resolve immediately (concepts may not be ready for the first query), or (c) move to a startup-time prewarm hook. Recommend (a) with WARN-log if first-resolve duration > 2s; revisit if profiling shows real impact.
- [ ] **PageIndex tree_id format convention** — *Owner: ETL team, follow-up issue*: the YAML schema accepts `pageindex_tree_id: string` as an opaque reference. The ETL team must pick a stable convention (likely `f"{tenant_id}::{document_id}::{version}"`) and document it. This spec does not lock the format; it only requires that `_indices[tree_id]` returns the right retriever.
- [ ] **`max_trees` cap for `search_documents_scoped`** — *Owner: Module 6 implementer*: 5 concepts × 3 docs = 15 trees would be an expensive query. Hard cap suggested at 10; expose as parameter on `SearchScopedInput` (default 10, not exposed to YAML). Confirm during Module 6 PR.
- [ ] **Partial index for `metadata->>'tenant_id'`** — *Owner: Module 4 implementer*: when the `concepts` namespace is created for the first time, should the migration code also create a partial GIN index on `(metadata->>'tenant_id')`? Recommend yes for the `concepts` table; the rest of the codebase that uses `metadata_filters` can opt in per-table.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-11 | Jesús Lara | Initial draft. Carries forward `concept-document-authority.brainstorm.md` (Option A). Locks the contract against FEAT-158 (`ontology-entity-extraction.spec.md`) as hard prerequisite. Sources of truth re-verified on 2026-05-11 against branch `dev`. |
