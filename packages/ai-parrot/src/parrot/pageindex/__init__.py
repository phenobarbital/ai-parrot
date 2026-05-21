"""PageIndex: Vectorless, reasoning-based RAG with hierarchical tree indexing.

Builds a semantic tree structure from PDF/Markdown documents and uses
LLM reasoning for agentic, context-aware retrieval.
"""
from .schemas import (
    PageIndexNode,
    TreeSearchResult,
    TocItem,
)
from .builder import build_page_index
from .md_builder import md_to_tree
from .retriever import PageIndexRetriever
from .llm_adapter import PageIndexLLMAdapter
from .store import JSONTreeStore
from .content_store import NodeContentStore
from .pdf_to_markdown import extract_markdown_per_page
from .tree_ops import splice_subtree, delete_node, reindex_node_ids
from .hybrid_search import HybridPageIndexSearch
from .ingest import TwoStepIngester, IngestedMarkdown
from .toolkit import PageIndexToolkit

__all__ = [
    "build_page_index",
    "md_to_tree",
    "PageIndexRetriever",
    "PageIndexLLMAdapter",
    "PageIndexNode",
    "TreeSearchResult",
    "TocItem",
    "JSONTreeStore",
    "NodeContentStore",
    "extract_markdown_per_page",
    "splice_subtree",
    "delete_node",
    "reindex_node_ids",
    "HybridPageIndexSearch",
    "TwoStepIngester",
    "IngestedMarkdown",
    "PageIndexToolkit",
]
