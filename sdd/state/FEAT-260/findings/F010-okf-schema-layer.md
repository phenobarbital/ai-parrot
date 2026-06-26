---
id: F010
query_id: Q010
type: read
intent: Deep dive into OKF as the wiki schema layer
executed_at: 2026-06-26T00:00:00Z
duration_ms: 5000
parent_id: F001
depth: 1
---

# F010 — OKF: The Wiki Schema Layer Already Exists

## Summary

The OKF (Ontology Knowledge Framework) at parrot/knowledge/okf/ and parrot/knowledge/pageindex/okf/ already provides nearly everything the wiki "schema layer" needs: (1) ConceptType enum with 16 semantic types (Section, Policy, Control, Symbol, Concept, Document, etc.), (2) RelationType enum with 13 relation types (references, maps_to, satisfies, defines, mentions, explains, contains, extends), (3) ConceptFrontmatter Pydantic model with type, title, id, resource URI, tags, timestamp, summary, relates_to, source provenance, (4) KnowledgeGraph class for in-memory adjacency with multi-hop traversal, (5) lint_knowledge_base() with 4 checks: orphan detection, broken link audit, missing concept pages, stale claims, (6) generate_index_md() for auto-generated content catalog, (7) OKF bundle import/export for round-trip I/O, (8) Deterministic concept_id assignment via slugified title paths, (9) byte-deterministic sidecar projection. The OKFToolkit exposes 9 agent tools: find_by_type, list_concepts, get_concept, get_related, trace_mapping, cite, lint_knowledge_base, export_okf_bundle, import_okf_bundle.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py`
  lines: 29-88
  symbol: `ConceptType, RelationType`
  excerpt: |
    class ConceptType(str, Enum):
        SECTION, POLICY, CONTROL, SAFEGUARD, EVIDENCE, PLAYBOOK,
        PROCEDURE, STANDARD, FRAMEWORK, REGULATION, GUIDELINE,
        SYMBOL, RATIONALE, SKILL, CONCEPT_NODE, DOCUMENT_NODE

- path: `packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py`
  lines: 35-63
  symbol: `ConceptFrontmatter`
  excerpt: |
    class ConceptFrontmatter(BaseModel):
        type: ConceptType
        title: str
        id: str  # concept_id — stable link target
        node_id: str
        resource: str  # pageindex://<tree>/<concept_id>
        tags: list[str]
        timestamp: str
        summary: str
        relates_to: list[RelatesTo]
        source: Optional[SourceProvenance]

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py`
  lines: 91-225
  symbol: `lint_knowledge_base`
  excerpt: |
    def lint_knowledge_base(graph, tree, content_store, stale_days=90) -> LintReport
    # Check 1: Orphan Detection (zero inbound edges)
    # Check 2: Broken Link Audit (edges to unknown concept_ids)
    # Check 3: Missing Concept Pages (no sidecar body)
    # Check 4: Stale Claims (older than stale_days)

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py`
  lines: 158-197
  symbol: `generate_index_md`

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py`
  lines: 73-237
  symbol: `KnowledgeGraph`

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py`
  lines: 46-362
  symbol: `OKFToolkit`

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py`
  lines: 1-584
  symbol: `export_okf_bundle, import_okf_bundle`

## Notes

CRITICAL FINDING: OKF is the natural foundation for the wiki schema layer. Rather than building a separate WikiSchema system, the LLMWiki should extend OKF with wiki-specific ConceptTypes (e.g., WIKI_SUMMARY, WIKI_ENTITY, WIKI_COMPARISON, WIKI_SYNTHESIS) and RelationTypes (e.g., SUMMARIZES, CONTRADICTS, SUPERSEDES). The lint engine maps directly to Karpathy's "lint" operation. The generate_index_md() maps to the index.md bookkeeping. The KnowledgeGraph class provides the cross-reference tracking. The OKFToolkit provides read tools; the wiki toolkit extends with write operations.
