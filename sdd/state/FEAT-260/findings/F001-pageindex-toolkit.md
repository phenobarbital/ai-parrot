---
id: F001
query_id: Q001
type: read
intent: Understand existing PageIndex toolkit and tree structure
executed_at: 2026-06-26T00:00:00Z
duration_ms: 2500
parent_id: null
depth: 0
---

# F001 — PageIndex Toolkit: Full-Featured Hierarchical Tree Index

## Summary

PageIndex is a mature, ~7,500 line module providing vectorless, reasoning-based RAG with hierarchical tree indexing. The `PageIndexToolkit` (1,262 lines) exposes 20+ agent-facing tools for managing named trees: create, search (hybrid BM25 + LLM walk + optional embeddings), retrieve, insert markdown/content, import files/PDFs/folders, delete/update nodes, and tag nodes. Storage is split: `<storage_dir>/<tree_name>.json` for lean ToC trees, `<storage_dir>/<tree_name>/` for sidecar markdown per node via `NodeContentStore`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`
  lines: 1-1262
  symbol: `PageIndexToolkit`
  excerpt: |
    class PageIndexToolkit(AbstractToolkit):
        name = "pageindex"
        tool_prefix = "pageindex"
        # Tools: list_trees, create_tree, delete_tree, get_tree, search,
        # retrieve, insert_markdown, insert_content, import_file, import_pdf,
        # import_folder, delete_node, add_node, update_node_content, update_node,
        # tag_node, search_documents_scoped

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py`
  lines: 118-150
  symbol: `PageIndexNode, PageIndexTree`
  excerpt: |
    class PageIndexNode(BaseModel):
        title: str
        node_id: Optional[str] = None
        start_index: Optional[int] = None
        end_index: Optional[int] = None
        summary: Optional[str] = None
        text: Optional[str] = None
        nodes: Optional[list[PageIndexNode]] = None

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py`
  lines: 1-97
  symbol: `JSONTreeStore`

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py`
  lines: 1-225
  symbol: `NodeContentStore`

- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py`
  lines: 1-462
  symbol: `HybridPageIndexSearch`

## Notes

PageIndex already provides tree-based document organization with search, but lacks wiki-specific operations: no index.md generation, no log tracking, no cross-reference maintenance, no lint. The `insert_markdown` and `add_node` tools handle individual page creation but not the orchestrated multi-page updates that Karpathy's ingest workflow requires.
