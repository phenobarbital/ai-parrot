---
id: F002
query_id: Q002
type: read
intent: Understand existing GraphIndex toolkit and knowledge graph
executed_at: 2026-06-26T00:00:00Z
duration_ms: 2200
parent_id: null
depth: 0
---

# F002 — GraphIndex Toolkit: Full Knowledge Graph with Community Detection

## Summary

GraphIndex is a mature, ~5,400 line module providing a 6-stage knowledge graph pipeline: Extract → Embed → Assemble → Resolve → Persist → Analyze. The `GraphIndexToolkit` (~1,200 lines, in parrot_tools) exposes 25+ tools: find_node, find_references, get_neighborhood, traverse, search_hybrid, find_central_nodes, shortest_path, explain, create_concept, create_node, link_nodes, unlink_nodes, attach_summary, tag_node, merge_nodes, relevance, neighborhood_by_relevance, list_communities, find_community, search_with_expansion, find_isolated_nodes, find_sparse_communities, find_bridge_nodes, dismiss_insight, list_unreviewed_insights. Uses rustworkx for in-memory graph operations and supports persistence to ArangoDB + SQLite.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 63-1225
  symbol: `GraphIndexToolkit`
  excerpt: |
    class GraphIndexToolkit(AbstractToolkit):
        # 25+ agent-facing tools for knowledge graph CRUD, traversal, search

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py`
  lines: 74-146
  symbol: `UniversalNode, UniversalEdge, NodeKind, EdgeKind`
  excerpt: |
    class NodeKind(str, Enum):
        DOCUMENT = "document"
        SECTION = "section"
        SYMBOL = "symbol"
        CONCEPT = "concept"
        RATIONALE = "rationale"
        SKILL = "skill"

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py`
  lines: 1-80
  symbol: `GraphExpandedRetriever, ExpansionConfig`

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py`
  lines: 1-441
  symbol: `Community, detect_communities`

## Notes

GraphIndex already captures entity relationships, concept graphs, and community structure. Key gap for wiki: no mechanism to automatically update the graph when a wiki page is created/modified, no wiki-page node kind, no cross-reference tracking between wiki pages as graph edges. The `create_concept` and `link_nodes` tools provide the primitives, but the wiki orchestration layer is missing.
