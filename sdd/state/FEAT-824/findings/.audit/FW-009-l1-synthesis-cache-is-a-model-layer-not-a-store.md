---
id: FW-009
query_id: Q209
type: wiki_query
intent: "GraphIndex L1 synthesis cache"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 3000
parent_id: null
depth: 1
---

# FW-009 — The L1 synthesis cache is `parrot/knowledge/retrieval/wiki_cache.py` (`WikiPage` / `WikiSection` keyed by source digests, per-section invalidation), not a `(repo, qualified_name, content_hash) → summary` table

## Summary

The L1 synthesis cache named by the draft exists as part of the GraphIndex Retrieval Layer (L2, FEAT-435): `retrieval/wiki_cache.py` defines `WikiPage` ("a structured L1 document anchored to one L0 subtree"), addressable `WikiSection`s, `SourceDigest` (`node_id`, `digest`, `digest_scope`), `GeneratorInfo` (model attribution), `compute_page_id(repo, scope_uri)`, per-section invalidation (`invalidate_section` / `invalidate_page` / `invalidate_ancestors`), coherence groups and a four-way serving decision (`resolve_serving_decision`). The module docstring states it is a different taxonomy **and a different store** from `parrot.knowledge.wiki`. The wiki page exposes only Pydantic models and pure functions — no persistence class surfaced in this lane. The draft's `synth` table (unique on `repo, qualified_name, content_hash`, one `summary` string, LWW by `content_hash`) is a much flatter model than the shipped section-level, multi-source, mixed-freshness design.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py`
  symbol: `WikiPage`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py
  score: 0.13 (query "retrieval wiki_cache WikiPage SourceDigest storage")
  excerpt: |
    """`WikiSection`/`WikiPage` — the L1 synthesis cache (spec §6).
    Splitting is a **retrieval-time selection over addressable sections** ... Because each section declares its
    own sources, editing one method invalidates only the `CONTRACTS` section of its class page ...
    Note: `WikiPage`/`WikiSection` are NOT `parrot.knowledge.wiki`'s `WikiPageCategory`/`SourceManifestEntry`
    (FEAT-260) — a different, orthogonal taxonomy and a different store. The two coexist (spec §14.3);
    this module does not import from `parrot.knowledge.wiki`.
    """

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py`
  symbol: `SourceDigest`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py
  excerpt: |
    class SourceDigest(BaseModel):
        """One `(node_id, digest)` pair a `WikiSection` declares as a source."""
        model_config = ConfigDict(frozen=True, extra="forbid")
        node_id: str
        digest: str
        digest_scope: DigestScope

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py`
  symbol: `resolve_serving_decision`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py
  excerpt: |
    def compute_page_id(repo, scope_uri): Compute a stable `WikiPage.page_id` from `(repo, scope_uri)`.
    def invalidate_section(section, current_digests): Transition `section` FRESH -> STALE if any of its sources moved.
    def invalidate_ancestors(): Invalidate `changed_node_id`'s own page, then walk ancestors upward.
    def compute_mixed_freshness(selected_sections): ``True`` iff sections do not all share one `coherence_group`.
    def resolve_serving_decision(): Resolve which serving behaviour applies (spec §6.3's serving matrix).

- path: `packages/ai-parrot/src/parrot/knowledge/retrieval/__init__.py`
  lines: 1-130
  symbol: `QueryClassifier`
  wiki_page_id: file:sdd/state/FEAT-778/findings/F044-graphindex-l2-retrieval.md
  score: 0.55 (Q209)
  excerpt: |
    `parrot/knowledge/retrieval/__init__.py` re-exports the L2 surface: `RetrievalRequest`, `RetrievalBudget`,
    `ContextBundle`/`ContextUnit`/`Evidence`/`EvidenceOrigin`, `QueryClassifier`/`RetrievalRoutingDecision`,
    escalation ladder, policies (`DirectSymbolPolicy`, `VectorSeedPolicy`, `Seed`, `Subgraph`), workspace pinning
    (`WorkspacePin`, ...), and the L1 wiki cache (`WikiPage`, `SourceDigest`, `compute_page_id`, ...).
    It consumes L0 `parrot.knowledge.graphindex` read-only.

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py`
  symbol: `_node_content_hash`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py#_node_content_hash
  score: 1.00 (Q209)
  excerpt: |
    Compute the stable no-op-detection hash for a node's persisted fields.

## Notes

- The draft's §6 flow names `QueryClassifier (L2)` — that symbol exists (`parrot.knowledge.retrieval`), so the "L0 / L1 / L2" vocabulary of the draft maps to: L0 = `parrot.knowledge.graphindex`, L1 = `retrieval/wiki_cache.py`, L2 = `parrot.knowledge.retrieval`.
- Where `WikiPage` objects are **persisted** today (if anywhere) was not answered by the wiki pages: the module page shows models + pure invalidation functions only. This decides whether "caché L1 → SurrealDB" replaces an existing store or creates the first one.
- `_node_content_hash` in `persist_postgres.py` is an L0 no-op-detection hash, unrelated to L1 synthesis; listed only because it was the top hit.
- [cross-lane: type=grep, intent=find the persistence of WikiPage/WikiSection (who reads/writes them: sqlite? files? none) under packages/ai-parrot/src/parrot/knowledge/retrieval and its callers]
