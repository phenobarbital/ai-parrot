"""Toolkit wrapper around the PageIndex indexing and retrieval pipeline."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from parrot.models.google import GoogleModel
from parrot.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.pageindex.md_builder import md_to_tree
from parrot.pageindex.retriever import PageIndexRetriever
from parrot.pageindex.utils import write_node_id
from parrot.tools.decorators import tool_schema
from parrot.tools.toolkit import AbstractToolkit

_MAX_TREES_HARD_CAP = 10


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


class SearchScopedInput(BaseModel):
    """Input schema for scoped multi-tree PageIndex search.

    Args:
        tree_ids: PageIndex tree IDs to scope the search to.
        query: Free-form natural-language query.
        include_tree_context: If True, include the per-tree tree_context blob
            in each scoped_results entry.
        max_trees: Hard cap on the number of trees searched. Defaults to 10.
    """

    tree_ids: list[str] = Field(
        ...,
        description="PageIndex tree IDs to scope the search to.",
    )
    query: str = Field(..., description="Free-form natural-language query.")
    include_tree_context: bool = Field(
        default=False,
        description="If true, include the per-tree tree_context blob in results.",
    )
    max_trees: int = Field(
        default=_MAX_TREES_HARD_CAP,
        ge=1,
        le=_MAX_TREES_HARD_CAP,
        description=(
            f"Hard cap on trees searched (default {_MAX_TREES_HARD_CAP}). "
            "Not exposed to YAML tool_call parameters."
        ),
    )

    model_config = ConfigDict(extra="forbid")


class PageIndexToolkit(AbstractToolkit):
    """Index markdown documents and search them with the PageIndex algorithm."""

    name = "pageindex"
    tool_prefix: str = "pageindex"
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

    @tool_schema(SearchScopedInput)
    async def search_documents_scoped(
        self,
        tree_ids: list[str],
        query: str,
        include_tree_context: bool = False,
        max_trees: int = _MAX_TREES_HARD_CAP,
    ) -> dict[str, Any]:
        """Search a SUBSET of indexed trees rather than the full collection.

        Iterates over the provided ``tree_ids`` and calls the existing
        ``PageIndexRetriever.search()`` + ``retrieve()`` for each.  Returns
        merged ``scoped_results`` with per-tree ``node_list``, ``thinking``,
        and ``context``.

        Missing tree IDs (not present in ``self._indices``) are silently
        skipped with a WARNING log.  Returns ``{"status": "empty"}`` when
        ``tree_ids`` is empty or when all provided IDs are missing.

        A hard cap of ``max_trees`` (default 10) limits the number of
        PageIndex LLM calls per invocation.  tree_ids beyond the cap are
        dropped and a DEBUG log is emitted.

        Args:
            tree_ids: PageIndex tree IDs to scope the search to.
            query: Free-form natural-language query.
            include_tree_context: If True, include the per-tree tree_context
                blob in each result entry.
            max_trees: Hard cap on trees searched (default and max 10).

        Returns:
            ``{"status": "ok", "scoped_results": [...]}`` or
            ``{"status": "empty", "scoped_results": []}``.

            Each entry in ``scoped_results`` has the shape::

                {
                    "tree_id":   str,
                    "doc_name":  str | None,
                    "node_list": list[str],
                    "thinking":  str,
                    "context":   str,
                    # only when include_tree_context=True:
                    "tree_context": str,
                }
        """
        if not tree_ids:
            return {"status": "empty", "scoped_results": []}

        # Apply hard cap
        effective_ids = tree_ids[:max_trees]
        if len(tree_ids) > max_trees:
            self.logger.debug(
                "search_documents_scoped: capping tree_ids from %d to %d",
                len(tree_ids),
                max_trees,
            )

        scoped_results: list[dict[str, Any]] = []

        for tree_id in effective_ids:
            record = self._indices.get(tree_id)
            if not record:
                self.logger.warning(
                    "search_documents_scoped: tree_id %r not found in _indices — skipping",
                    tree_id,
                )
                continue

            retriever: PageIndexRetriever = record["retriever"]
            tree_data: dict[str, Any] = record.get("tree", {})
            doc_name: str | None = tree_data.get("doc_name")

            search_result = await retriever.search(query)
            context = await retriever.retrieve(query)

            entry: dict[str, Any] = {
                "tree_id": tree_id,
                "doc_name": doc_name,
                "node_list": search_result.node_list,
                "thinking": search_result.thinking,
                "context": context,
            }
            if include_tree_context:
                entry["tree_context"] = retriever.get_tree_context(
                    include_summaries=True
                )

            scoped_results.append(entry)

        if not scoped_results:
            return {"status": "empty", "scoped_results": []}

        return {"status": "ok", "scoped_results": scoped_results}
