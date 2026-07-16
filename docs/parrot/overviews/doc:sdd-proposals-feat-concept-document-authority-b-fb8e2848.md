---
type: Wiki Overview
title: FEAT-concept-document-authority — Brainstorm
id: doc:sdd-proposals-feat-concept-document-authority-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Pure vector RAG cannot reliably answer authority-grounded questions like
  *"how do commissions work?"* because semantic similarity does not capture **document
  authority** within a corpus. This feature introduces `Document` and `Concept` as
  first-class ontology entities, a curated '
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.knowledge.ontology
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# FEAT-concept-document-authority — Brainstorm

**Status:** brainstorm
**Type:** retrieval architecture
**Dependencies:** FEAT-ontology-entity-extraction, existing `PageIndexToolkit`, existing `OntologyRAGMixin`, PgVector store
**Drives:** FEAT-topic-authority-operational
**Owner:** TBD

---

## Summary

Pure vector RAG cannot reliably answer authority-grounded questions like *"how do commissions work?"* because semantic similarity does not capture **document authority** within a corpus. This feature introduces `Document` and `Concept` as first-class ontology entities, a curated `covers_topic` relation with explicit authority (`primary | secondary | mentions`), and a traversal pattern that routes from query → concept → authoritative document → PageIndex tree-search within that document → optional vector refinement.

PageIndex retains its current role as the **intra-document navigator**. The new layer is a routing layer that decides *which* PageIndex tree to feed to the retriever for a given query, based on declared topic authority rather than embedding similarity over the full corpus.

---

## Motivation

Vector RAG over a corporate corpus produces a class of high-confidence false positives:

- *"How do commissions work?"* → retrieves a critical memo titled *"Why our commissions are not working"* instead of the canonical Sales Commissions Policy.
- *"What is our PTO policy?"* → retrieves an FAQ that paraphrases the policy instead of the policy itself.
- *"Refund process?"* → retrieves a customer-service training document instead of the operational SOP.

The error mode is structural: **authority is not a property of content, it is a property of the document's role in the corpus**, declared by the organization. Embeddings cannot recover this signal post-hoc, no matter how well-tuned the model.

A graph layer with curated `covers_topic` edges + authority qualifier captures this signal natively and survives content paraphrase, document version updates, and multilingual corpora. PageIndex already provides high-quality intra-document retrieval via LLM tree-search; it just lacks a routing layer that asserts *"for this concept, search inside THIS document, not the whole corpus"*.

---

## Goals

- Introduce `Document`, `Concept`, and (optionally) `Section` as first-class ontology entities.
- Introduce `covers_topic` relation between `Document` and `Concept` with `authority ∈ {primary, secondary, mentions}`.
- Introduce `is_a` relation between `Concept`s for taxonomic queries (e.g. asking about "commissions" pulls in "sales commissions" as descendant).
- Add traversal pattern `authoritative_doc_for_topic` that combines graph routing + PageIndex search.
- Extend `PageIndexToolkit` with `search_documents_scoped(tree_ids, query)` to support pre-filtered tree retrieval.
- Implement `hybrid_concept_match` resolver strategy (synonym → vector → LLM) building on `EntityResolver` from FEAT-ontology-entity-extraction.
- Provide a **graceful degradation chain** when concept extraction fails (relax authority → filtered vector → plain vector), with response labeled by source for transparency.

## Non-goals

- The operational mechanism for curating `covers_topic` edges — that is FEAT-topic-authority-operational. This feature treats edges as already populated (YAML or seed).
- New PageIndex tree builders or extractors.
- Replacing vector search; vector remains the recall safety net.
- `Concept` lifecycle management (creation, merging, deprecation) UI — deferred.

---

## Codebase contract

### What exists today

- `parrot.pageindex.PageIndexRetriever`: LLM-driven tree-search over `{title, summary, nodes}` hierarchy.
- `parrot.tools.pageindex_toolkit.PageIndexToolkit`: indexes documents into trees, retrieves by `index_id`. Tools: `index_documents`, `search_documents`.
- `parrot.knowledge.ontology.*`: full ontology stack post-FEAT-ontology-entity-extraction, including `EntityResolver` and `ToolCallDispatcher`.
- `parrot.bots.mixins.intent_router.IntentRouterMixin._run_graph_pageindex`: currently tries `ontology_process` → `graph_store.query` → `pageindex_retriever.retrieve` as a parallel cascade.
- PgVector store for vectorized content.
- `parrot.knowledge.ontology.tenant.TenantOntologyManager` for per-tenant ontology resolution.

### What this feature builds

- YAML layer `knowledge.ontology.yaml` adding `Document`, `Concept` entities and `covers_topic`, `is_a` relations.
- `hybrid_concept_match` strategy added to `EntityResolver` (synonym → vector → LLM).
- **Concept embedding pipeline**: on ontology load, vectorize `label + synonyms + description` into a dedicated PgVector namespace (`{tenant}_concepts`). Hashed for change detection.
- `PageIndexToolkit.search_documents_scoped(tree_ids, query)` method.
- New traversal pattern `authoritative_doc_for_topic` using `post_action: tool_call → PageIndexToolkit.search_documents_scoped`.
- Refactor `IntentRouterMixin._run_graph_pageindex` to drive PageIndex *through* the ontology rather than as a parallel cascade.

---

## Proposed design

### YAML — new layer

```yaml
name: knowledge
extends: base
version: "1.0"

entities:
  Document:
    collection: documents
    source: confluence                # or sharepoint / gdrive — pluggable
    key_field: document_id
    properties:
      - document_id:       { type: string, required: true, unique: true }
      - title:             { type: string, required: true }
      - doc_type:          { type: string, enum: ["policy","manual","memo","guide","faq"] }
      - version:           { type: string }
      - effective_date:    { type: date }
      - is_current:        { type: boolean, default: true }
      - authority_score:   { type: float, default: 0.5,
                             description: "0..1, signal weight when multiple primaries match" }
      - pageindex_tree_id: { type: string,
                             description: "Opaque reference to a PageIndex tree" }
      - language:          { type: string, default: "en" }
    vectorize:
      - title                          # ONLY title here; chunks go via PageIndex

  Concept:
    collection: concepts
    key_field: concept_id
    properties:
      - concept_id:  { type: string, required: true, unique: true }
      - label:       { type: string, required: true }
      - synonyms:    { type: list }
      - description: { type: string }
      - domain:      { type: string,
                       description: "Disambiguates: 'finance', 'hr', 'sales'" }
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
      - authority:    { type: string, enum: ["primary","secondary","mentions"], required: true }
      - confidence:   { type: float, default: 1.0 }
      - asserted_by:  { type: string, description: "Curator id or 'auto:ner_v1'" }

  is_a:
    from: Concept
    to: Concept
    edge_collection: concept_is_a
```

### Traversal pattern

```yaml
authoritative_doc_for_topic:
  description: >
    Route topical queries through curated authority edges into PageIndex.
    Walks Concept taxonomy via is_a so sub-concepts are included.

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
    LET concept = DOCUMENT(@topic_id)
    LET concept_family = (
      FOR sub IN 0..3 INBOUND concept._id @@concept_is_a
        RETURN sub._id
    )
    FOR doc IN documents
      FOR edge IN doc_covers_concept
        FILTER edge._from == doc._id
        FILTER edge._to IN concept_family
        FILTER doc.is_current == true
        FILTER edge.authority == "primary"
        SORT doc.authority_score DESC, doc.effective_date DESC
        LIMIT 3
        RETURN {
          document_id:       doc.document_id,
          title:             doc.title,
          doc_type:          doc.doc_type,
          version:           doc.version,
          pageindex_tree_id: doc.pageindex_tree_id,
          matched_concept:   concept.label,
          authority:         edge.authority
        }

  post_action: tool_call
  tool_call:
    toolkit: PageIndexToolkit
    method: search_documents_scoped
    parameters:
      tree_ids: "{{ graph.rows | map_attr('pageindex_tree_id') | json }}"
      query:    "{{ ctx.original_query }}"
      include_tree_context: false
    result_binding: pageindex_hits
    empty_team_behavior: short_circuit
```

### Hybrid concept matching algorithm

Implemented as a new resolver strategy in `EntityResolver`:

```python
async def hybrid_concept_match(query, ontology, llm, threshold=0.85):
    # 1. Synonym/fuzzy exact match — if dominant, accept.
    syn_hit = synonym_match(query, ontology.concepts)
    if syn_hit and syn_hit.confidence > 0.95:
        return syn_hit

    # 2. Vector match top-K against Concept embeddings.
    candidates = await vector_match_concepts(query, ontology, top_k=10)
    if not candidates:
        return None
    if candidates[0].score > threshold and candidates[0].score > candidates[1].score * 1.3:
        return candidates[0]   # clearly dominant top candidate

    # 3. LLM tie-breaker over top-5 candidates.
    return await llm_classify_concept(query, candidates[:5], llm)
```

The `1.3×` margin is empirical: if the top concept doesn't dominate, the LLM disambiguates. In practice ~60–70% of queries are resolved without LLM.

Cache hybrid_concept_match results by `(query_hash, ontology_version)` — concept extraction is expensive and queries repeat heavily.

### Graceful degradation chain

When concept extraction returns nothing OR no primary edge matches:

1. Relax to `authority == "secondary"` — retry traversal.
2. Fall back to vector RAG **filtered by `doc_type IN ('policy', 'manual')`** — narrows recall to authoritative-ish doc types.
3. Fall back to plain vector RAG.
4. Always tag `EnrichedContext.source` so the agent can disclose: *"I didn't find an authoritative document; this is from semantic search"*.

### Concept embedding pipeline

On `TenantOntologyManager.resolve()`:

- Compute `concept_hash = sha256(label + sorted(synonyms) + description)` per Concept.
- Compare against stored hashes in `{tenant}_concepts_index`.
- For changed/new concepts, embed and upsert into PgVector namespace.
- Removed concepts → delete from namespace.

Idempotent and fast (~ms for cached, ~seconds for first load).

### PageIndexToolkit extension

```python
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
    """
    results = []
    for tree_id in tree_ids:
        record = self._indices.get(tree_id)
        if not record:
            continue
        retriever: PageIndexRetriever = record["retriever"]
        search_result = await retriever.search(query)
        context = await retriever.retrieve(query)
        results.append({
            "tree_id":   tree_id,
            "doc_name":  record["tree"].get("doc_name"),
            "node_list": search_result.node_list,
            "thinking":  search_result.thinking,
            "context":   context,
        })
    return {"status": "ok", "scoped_results": results}
```

Zero duplication with existing PageIndex code — just restricts the iteration domain.

### IntentRouterMixin._run_graph_pageindex refactor

Today:

```python
# Cascade: ontology_process → graph_store.query → pageindex_retriever.retrieve
```

After:

```python
async def _run_graph_pageindex(self, prompt, candidates):
    if hasattr(self, "ontology_process"):
        result = await self.ontology_process(
            query=prompt,
            user_context=self._get_permission_context(),
            tenant_id=getattr(self, "_tenant_id", "default"),
        )
        if result.source == "graph" and getattr(result, "pageindex_hits", None):
            return self._format_with_provenance(result)
        if result.source == "ambiguous":
            return self._format_clarification(result)
        if result.source in ("denied", "auth_required"):
            return self._format_meta_response(result)
        # Otherwise fall through to standalone PageIndex (recall safety net).

    retriever = getattr(self, "_pageindex_retriever", None) or getattr(
        self, "pageindex_retriever", None,
    )
    if retriever:
        try:
            return await retriever.retrieve(prompt)
        except Exception:
            return None
    return None
```

The fallback to unscoped PageIndex is intentional: it handles queries where no concept is modeled yet, and the answer might still live in a PageIndex tree somewhere. Vector RAG sits one tier below.

---

## Implementation plan

1. **YAML schema extension** + golden loading/merger tests.
2. **Concept embedding pipeline**: extend `TenantOntologyManager` to vectorize concepts at tenant init with change detection.
3. **`hybrid_concept_match` strategy** in `EntityResolver` (extends FEAT-ontology-entity-extraction).
4. **`PageIndexToolkit.search_documents_scoped`**.
5. **Wire traversal pattern** — reuses `ToolCallDispatcher` from FEAT-ontology-entity-extraction; no new components.
6. **Graceful degradation logic** in `OntologyRAGMixin.ontology_process` — secondary relax + filtered vector + plain vector fallback chain.
7. **Refactor `IntentRouterMixin._run_graph_pageindex`** to drive PageIndex via ontology.
8. **End-to-end tests**:
   - Known concept → authoritative doc → correct PageIndex hits.
   - Unknown concept → falls through to vector, response labeled.
   - Multiple primaries → ordered by `authority_score`.
   - Sub-concept query → parent's documents returned via `is_a` walk.
   - Concept synonyms updated → re-embedding triggered.

---

## Open questions

- **`Section` as entity, yes or no?** Brings finer-grained graph traversal at the cost of ETL complexity and graph size. **Recommendation:** ship without `Section`; add only if a use case requires cross-section linking or section-level authority.
- **Multi-document responses.** If 3 primaries match (regional + global + adendum), pass all to LLM with type labels? **Recommendation:** yes; label each with `doc_type` and let the LLM compose with awareness of overlap.
- **Concept hierarchy depth.** `0..3 INBOUND concept_is_a` is sufficient for most taxonomies; deeper risks combinatorial explosion. Document as tunable per tenant.
- **Concept synonyms across languages.** Single `synonyms` list mixing languages or per-language lists? **Recommendation:** single list with normalization at match time; re-evaluate if multilingual tenants surface concrete pain.
- **Authority tie-break beyond `authority_score`.** When score is identical (common at seed time), what's the rule? **Recommendation:** `effective_date DESC` as secondary, `created_at DESC` as tertiary, deterministic across runs.

---

## Acceptance criteria

- *"How do commissions work?"* routes to the document with `covers_topic[authority=primary]` for the Commissions concept, regardless of which other documents mention commissions.
- A new Concept added to YAML is automatically embedded into the concept vector namespace at tenant init.
- A modified Concept (synonym added) re-embeds; the old embedding is replaced.
- A query with no concept match falls through to vector RAG and is labeled `source="vector_fallback"` in the `EnrichedContext`.
- Taxonomic query: a query about a parent concept returns documents linked to descendant concepts via `is_a`.
- A PDF/Markdown indexed into PageIndex can be searched via `search_documents_scoped` with the same fidelity as the unscoped `search_documents`.
- When two primaries have equal `authority_score`, ordering is deterministic across consecutive runs.

---

## Risks

- **Concept ontology bloat.** Without governance, every domain noun becomes a Concept. **Mitigation:** FEAT-topic-authority-operational introduces operational lifecycle.
- **Authority drift.** Documents change but edges don't follow. **Mitigation:** ETL emits "stale edge" alerts when a `Document.version` increments without corresponding edge review.
- **Vector index inconsistency.** Concept embeddings go stale on synonym changes. **Mitigation:** content-hash-based re-embedding pipeline (above).
- **Edge case — concept matches but no primary exists.** A concept is modeled in the ontology, but no document has been mapped as primary yet. **Mitigation:** graceful degradation chain (secondary → filtered vector → plain vector), with `EnrichedContext.source` labeled so the agent discloses.
- **PageIndex tree IDs out of sync with `Document.pageindex_tree_id`.** Document deleted from PageIndex but graph still references it. **Mitigation:** `search_documents_scoped` silently skips missing tree_ids; emit warning log.

---

## References

- FEAT-ontology-entity-extraction — provides `EntityResolver`, `ToolCallDispatcher`, schema extensions used here.
- FEAT-topic-authority-operational — operational truth for `covers_topic` edges.
- `packages/ai-parrot/src/parrot/pageindex/` — PageIndex implementation.
- `packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py` — PageIndex toolkit.
