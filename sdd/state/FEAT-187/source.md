---
kind: file
jira_key: null
fetched_at: 2026-05-19
summary_oneline: GraphIndex — structured knowledge graph indexing unifying code, docs, and skills via pipeline-of-stages build
---

# Source: sdd/proposals/graphindex.proposal.md

Comprehensive brainstorm/proposal for a `GraphIndex` feature that provides structured-knowledge graph
indexing across source code (Python, TS, Svelte via tree-sitter), structured documentation (PDF, DOCX,
Markdown, web, ebook, audio, video via ai-parrot-loaders), and SKILL.md files.

**Recommended architecture**: Option B — Pipeline of stages with eager embeddings, FAISS hot + ArangoDB persistent.

Six-stage build pipeline:
1. Extract (code path via tree-sitter + loader path via ai-parrot-loaders/PageIndex)
2. Embed (batch embedding → FAISS + pgvector)
3. Assemble (rustworkx PyDiGraph)
4. Resolve cross-domain (Level 1 embedding-threshold)
5. Persist (OntologyGraphStore → ArangoDB + pgvector)
6. Analyze + Report (centrality, GRAPH_REPORT.md)

Agent-facing `GraphIndexToolkit` exposes: find_node, find_references, get_neighborhood, traverse,
search_hybrid, find_central_nodes, shortest_path, explain.

Key integration points:
- `parrot.knowledge.ontology.graph_store.OntologyGraphStore` — persistence backend
- `parrot.pageindex` — tree builders for hierarchical content
- `parrot_loaders` — content acquisition for non-code formats
- `parrot.tools.AbstractToolkit` — toolkit base class
- `parrot.bots.prompts.layers.KNOWLEDGE_LAYER` — GRAPH_REPORT.md injection

Refresh: full reindex via Flowtask component + incremental per-document via ingest_document(uri) API.

New module: `parrot.knowledge.graphindex`
New dependencies: rustworkx, tree-sitter, tree-sitter-languages, pathspec (new [graphindex] extra)
