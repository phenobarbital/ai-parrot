"""Toolkit wrapper around the PageIndex indexing and retrieval pipeline."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.models.google import GoogleModel
from parrot.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.pageindex.md_builder import md_to_tree
from parrot.pageindex.retriever import PageIndexRetriever
from parrot.pageindex.utils import write_node_id
from parrot.tools.decorators import tool_schema
from parrot.tools.toolkit import AbstractToolkit


class IndexDocumentsInput(BaseModel):
    """Input schema for PageIndex document indexing."""

    documents: list[str] = Field(..., min_length=1, description="Markdown/text documents to index.")
    document_names: Optional[list[str]] = Field(
        default=None,
        description="Optional names aligned 1:1 with `documents`.",
    )


class SearchDocumentsInput(BaseModel):
    """Input schema for PageIndex search."""

    index_id: str = Field(..., description="Index ID returned by index_documents.")
    query: str = Field(..., min_length=1, description="Natural-language search query.")
    include_tree_context: bool = Field(
        default=False,
        description="Include formatted tree context in the response.",
    )


class PageIndexToolkit(AbstractToolkit):
    """Index markdown documents and search them with the PageIndex algorithm."""

    name = "pageindex"
    description = (
        "Toolkit for document indexing and retrieval using PageIndex tree-search "
        "with Google Gemini Flash Lite."
    )

    def __init__(
        self,
        model: str = GoogleModel.GEMINI_3_FLASH_LITE_PREVIEW.value,
        client: Any | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.model = model
        if client is None:
            from parrot.clients.google import GoogleGenAIClient

            client = GoogleGenAIClient(model=model)
        self._client = client
        self._adapter = PageIndexLLMAdapter(client=self._client, model=model)
        self._indices: dict[str, dict[str, Any]] = {}

    async def stop(self) -> None:
        """Close the underlying LLM client when supported."""
        close_fn = getattr(self._client, "close", None)
        if callable(close_fn):
            await close_fn()

    @tool_schema(IndexDocumentsInput)
    async def index_documents(
        self,
        documents: list[str],
        document_names: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Build a PageIndex tree for one or more markdown/text documents."""
        if document_names and len(document_names) != len(documents):
            raise ValueError("document_names must match documents length")

        merged_structure: list[dict[str, Any]] = []
        normalized_names = document_names or [f"document_{idx + 1}.md" for idx in range(len(documents))]

        for idx, content in enumerate(documents):
            doc_name = normalized_names[idx]
            doc_tree = await md_to_tree(
                md_text=content,
                adapter=self._adapter,
                doc_name=doc_name,
                options={"model": self.model},
            )

            doc_node = {
                "title": doc_name,
                "summary": f"Indexed source document: {doc_name}",
                "nodes": doc_tree.get("structure", []),
            }
            merged_structure.append(doc_node)

        write_node_id(merged_structure)
        tree = {"doc_name": "pageindex_collection", "structure": merged_structure}
        index_id = str(uuid.uuid4())
        retriever = PageIndexRetriever(tree=tree, adapter=self._adapter, model=self.model)
        self._indices[index_id] = {"tree": tree, "retriever": retriever}

        return {
            "status": "indexed",
            "index_id": index_id,
            "model": self.model,
            "document_count": len(documents),
        }

    @tool_schema(SearchDocumentsInput)
    async def search_documents(
        self,
        index_id: str,
        query: str,
        include_tree_context: bool = False,
    ) -> dict[str, Any]:
        """Search an existing PageIndex index and return matching context."""
        record = self._indices.get(index_id)
        if not record:
            return {
                "status": "not_found",
                "message": f"Unknown index_id: {index_id}",
            }

        retriever: PageIndexRetriever = record["retriever"]
        search_result = await retriever.search(query)
        context = await retriever.retrieve(query)

        response: dict[str, Any] = {
            "status": "ok",
            "index_id": index_id,
            "query": query,
            "thinking": search_result.thinking,
            "node_list": search_result.node_list,
            "context": context,
        }
        if include_tree_context:
            response["tree_context"] = retriever.get_tree_context(include_summaries=True)
        return response
