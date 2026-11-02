---
id: FC-012
query_id: Q031
type: read
intent: "GraphIndex retrieval public API and policies (what `source: graphindex, mode: retrieval` calls)."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-012 — `parrot.knowledge.retrieval` (L2, FEAT-435) exposes policies (`DirectSymbolPolicy`, `VectorSeedPolicy`, `RetrievalPolicy` protocol), digests, pins and escalation over a read-only L0 GraphIndex

## Summary

151-line package init. Re-exports classifier, `DigestScope`/`derive_digest`, escalation, `IndexPinMismatchError`/`StalePinError`, `QueryFeatures`/`extract_features`, lexicon, models, pin, and `policies` (`DirectSymbolPolicy`, `RetrievalPolicy`, `RetrievalPolicyProtocol`, `VectorSeedPolicy`). The design doc is `sdd/specs/graphindex-retriever.spec.md`. An expert's `graphindex` retrieval source would bind to these policies; index pins give the "revision" handle for the KnowledgeContext.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py`
  lines: 1-15
  symbol: `module docstring`
  excerpt: |
    Turns a natural-language question into a bounded, attributable ...
    This package consumes parrot.knowledge.graphindex (L0) **read-only**
    See sdd/specs/graphindex-retriever.spec.md (FEAT-435)

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py`
  lines: 18-66
  symbol: `re-exports`
  excerpt: |
    from parrot.knowledge.retrieval.digest import DigestScope, derive_digest
    from parrot.knowledge.retrieval.exceptions import IndexPinMismatchError, StalePinError
    from parrot.knowledge.retrieval.pin import (...)
    from parrot.knowledge.retrieval.policies import (DirectSymbolPolicy, RetrievalPolicy, RetrievalPolicyProtocol, VectorSeedPolicy)

## Notes

No findings on L1 wiki cache details here; `retrieval/wiki_cache.py` and `digest.py` hold the digest logic (FC-013).
