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

__all__ = [
    "build_page_index",
    "md_to_tree",
    "PageIndexRetriever",
    "PageIndexLLMAdapter",
    "PageIndexNode",
    "TreeSearchResult",
    "TocItem",
]
