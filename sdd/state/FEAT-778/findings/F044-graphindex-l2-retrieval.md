---
id: F044
query_id: Q007
type: wiki_page
intent: "GraphIndex L2 retrieval layer public API"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FW-007-graphindex-l2-retrieval]
---

# F044 — GraphIndex L2 (FEAT-435) exposes `RetrievalRequest/RetrievalBudget → ContextBundle` with policies (`DirectSymbolPolicy`, `VectorSeedPolicy`), a `WorkspacePin`, and an L1 wiki cache with `SourceDigest` invalidation

## Summary

`parrot/knowledge/retrieval/__init__.py` re-exports the L2 surface: `RetrievalRequest`, `RetrievalBudget`, `ContextBundle`/`ContextUnit`/`Evidence`/`EvidenceOrigin` (attributable units), `QueryClassifier`/`RetrievalRoutingDecision`, escalation ladder (`run_escalation_ladder`, `SufficiencyCheck`), policies (`RetrievalPolicy`, `RetrievalPolicyProtocol`, `DirectSymbolPolicy`, `VectorSeedPolicy`, `Seed`, `Subgraph`), workspace pinning (`WorkspacePin`, `resolve_workspace`, `check_pin_coherence`, `StalePinError`), and the L1 wiki cache (`WikiPage`, `SourceDigest`, `compute_page_id`, `invalidate_page/section/ancestors`, `resolve_serving_decision`). It consumes L0 `parrot.knowledge.graphindex` read-only.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py`
  lines: 1-130
  symbol: `RetrievalRequest, RetrievalBudget, ContextBundle, RetrievalPolicy, WorkspacePin, SourceDigest`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py
  score: 0.98
  excerpt: |
    from parrot.knowledge.retrieval.models import (RESERVED_ORIGINS, ContextBundle, ContextUnit, EdgeRef,
        Evidence, EvidenceOrigin, NodeRef, RetrievalBudget, RetrievalRequest)
    from parrot.knowledge.retrieval.policies import (DirectSymbolPolicy, RetrievalPolicy,
        RetrievalPolicyProtocol, Seed, Subgraph, VectorSeedPolicy)
    from parrot.knowledge.retrieval.wiki_cache import (SourceDigest, WikiPage, compute_page_id,
        invalidate_ancestors, invalidate_page, invalidate_section, resolve_serving_decision)

- path: `sdd/specs/graphindex-retriever.spec.md`
  symbol: `FEAT-435`
  wiki_page_id: file:sdd/specs/graphindex-retriever.spec.md
  score: 0.94
  excerpt: |
    Feature Specification: GraphIndex Retrieval Layer

## Notes

`source: graphindex, mode: retrieval` in the manifest has a concrete target: `RetrievalRequest` + `RetrievalBudget` → `ContextBundle`, already budgeted and attributable (`EvidenceOrigin`). A `KnowledgeContext.layers[retrieval]` entry can hold the `WorkspacePin` + budget instead of content. `SourceDigest`-based invalidation is the in-repo precedent for the source's DocumentKB "digest → summary invalidation" rule.
